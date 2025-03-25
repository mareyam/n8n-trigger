import gspread
import pandas as pd
import requests
from bs4 import BeautifulSoup
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials
import openai
from googleapiclient.discovery import build
from google.oauth2 import service_account
from dotenv import load_dotenv
import os
import openai
from fastapi import FastAPI, HTTPException
from fastapi import FastAPI
from pydantic import BaseModel
import asyncio

app = FastAPI()

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
google_project_id = os.getenv("GOOGLE_PROJECT_ID")
google_private_key_id = os.getenv("GOOGLE_PRIVATE_KEY_ID")
google_private_key = os.getenv("GOOGLE_PRIVATE_KEY")
google_client_email = os.getenv("GOOGLE_CLIENT_EMAIL")
google_client_id = os.getenv("GOOGLE_CLIENT_ID")
google_auth_uri = os.getenv("GOOGLE_AUTH_URI")
google_token_uri = os.getenv("GOOGLE_TOKEN_URI")
google_cert_url = os.getenv("GOOGLE_CERT_URL")
google_x509_cert_url = os.getenv("GOOGLE_X509_CERT_URL")
DOCUMENT_ID = os.getenv("DOCUMENT_ID")

SCOPES = ["https://www.googleapis.com/auth/documents"]
SERVICE_ACCOUNT_FILE = "google-credentials.json"

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
docs_service = build("docs", "v1", credentials=credentials)

@app.get("/")
def read_root():
    return {"message": "Hello World"}

@app.get("/hi")
def hi():
    return {"message": "Hello World"}

@app.post("/fun1")
async def fun1():
    try:
        title = await generate_amazon_title()
        return title
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error triggering functions: {e}")

@app.post("/trigger")
async def trigger_functions():
    try:
        # Call the functions here
        print("Generating Google Sheet:")

        match_and_create_google_sheet(credentials_file, amazon_sheet_url, scrap_sheet_url, output_sheet_url, product_url)
       
        print("Generating Google Docs:")
        keywords = await generate_amazon_backend_keywords()
        bullets = await generate_amazon_bullets()
        desc = await generate_amazon_description()
        title = await generate_amazon_title()
        print("Results Generated")
        return {"keywords": keywords, "bullets": bullets,"desc": desc, "title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error triggering functions: {e}")

def append_to_google_doc(doc_id, text):
    """Append text to a Google Doc."""
    requests = [
        {
            "insertText": {
                "location": {"index": 1},
                "text": text + "\n\n"
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def authenticate_gspread(credentials_file):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)
    return gspread.authorize(creds)

def get_google_sheet_data(gc, sheet_url):
    sheet = gc.open_by_url(sheet_url).sheet1
    df = get_as_dataframe(sheet, evaluate_formulas=True, skip_blank_rows=True)
    return df.dropna(how="all")

def scrape_product_info(product_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(product_url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to fetch product page: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        title = soup.find("span", {"id": "productTitle"})
        price = soup.find("span", {"class": "a-price-whole"})
        description = soup.find("div", {"id": "feature-bullets"})

        product_info = {
            "title": title.text.strip() if title else "N/A",
            "price": price.text.strip() if price else "N/A",
            "description": description.text.strip() if description else "N/A"
        }
        return product_info
    
    except Exception as e:
        print(f"Error scraping product info: {e}")
        return None

def get_product_summary(product_info):
    if not product_info:
        return "No product details available."
    
    summary = f"{product_info['title']} - {product_info['price']}. {product_info['description'][:100]}..."
    return summary

def get_top_matches(product_info, field_name, field_values):
    """Uses OpenAI to find the best matches for a given field from the product description."""

    client = openai.OpenAI(api_key="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")

    ai_prompt = f"""
    # You are an AI model that matches structured product fields with valid values.
    # Product Description: {product_info}
    # Field: {field_name}
    # Valid Values: {field_values}

    # Return the best matching values (max 5) in a comma-separated format without extra characters.
    """

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": ai_prompt}]
    )
    
    matches = response.choices[0].message.content.strip().split(", ")

    return [match for match in matches if match]

def match_and_create_google_sheet(credentials_file, amazon_sheet_url, scrap_sheet_url, output_sheet_url, product_url):
    gc = authenticate_gspread(credentials_file)
    amazon_df = get_google_sheet_data(gc, amazon_sheet_url)
    scrap_df = get_google_sheet_data(gc, scrap_sheet_url)
    
    amazon_fields = set(amazon_df.iloc[1:, 0].dropna())
    scrap_fields = set(scrap_df.iloc[1:, 0].dropna())
    matching_fields = list(amazon_fields.intersection(scrap_fields))
    
    product_info = scrape_product_info(product_url)
    product_summary = get_product_summary(product_info) if product_info else ""

    if matching_fields:
        matched_data = {"Field Name": [], "Value": [], "AI Best Matched 1": [], "AI Best Matched 2": [], "AI Best Matched 3": [], "AI Best Matched 4": [], "AI Best Matched 5": []}
        
        for field in matching_fields:
            matched_data["Field Name"].append(field)
            value = amazon_df.loc[amazon_df.iloc[:, 0] == field].iloc[:, 1].values
            matched_value = value[0] if len(value) > 0 else ""
            
            # AI Matching
            ai_matches = get_top_matches(product_summary, field, matched_value) if product_info else []
            
            # Ensure there are exactly 5 matches (if fewer, leave empty)
            ai_matches = ai_matches[:5]  # Get only the first 5 matches
            ai_matches += [""] * (5 - len(ai_matches))  # Pad with empty strings if less than 5 matches
            
            matched_data["Value"].append(matched_value)
            matched_data["AI Best Matched 1"].append(ai_matches[0])
            matched_data["AI Best Matched 2"].append(ai_matches[1])
            matched_data["AI Best Matched 3"].append(ai_matches[2])
            matched_data["AI Best Matched 4"].append(ai_matches[3])
            matched_data["AI Best Matched 5"].append(ai_matches[4])

        matched_df = pd.DataFrame(matched_data)

        # Write to Google Sheets
        output_sheet = gc.open_by_url(output_sheet_url).worksheet("Test")
        output_sheet.clear()
        set_with_dataframe(output_sheet, matched_df)

        print(f"Matching fields with values saved in Google Sheet: {output_sheet_url} (Sheet: Test)")
    else:
        print("No matching fields found.")


async def generate_amazon_title():
    try:
        response = await asyncio.to_thread(client.chat.completions.create,
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "You are an expert in writing Amazon product titles."},
                {"role": "user", "content": title_prompt}
            ]
        )
        title = response.choices[0].message.content.strip()
        print("Generated Amazon Product Title")
        append_to_google_doc(DOCUMENT_ID, f"Amazon Product Title:\n{title}")
        return title
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating title: {str(e)}")

async def generate_amazon_bullets():
    try:
        response = await asyncio.to_thread(client.chat.completions.create,
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "You are an expert in writing Amazon product bullet points."},
                {"role": "user", "content": bullets_prompt}
            ]
        )
        bullets = response.choices[0].message.content.strip()
        print("Generated Amazon Bullet Points")
        append_to_google_doc(DOCUMENT_ID, f"Amazon Bullet Points:\n{bullets}")
        return bullets
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating title: {str(e)}")

async def generate_amazon_backend_keywords():
    try:
        if not product_url:
            return "Failed to generate backend keywords: No product data found"
        response = await asyncio.to_thread(client.chat.completions.create,
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": keywords_prompt}]
        )
        
        backend_keywords = response.choices[0].message.content.strip()
        print("Generated Amazon Product Keywords")
        append_to_google_doc(DOCUMENT_ID, f"Amazon Product Keywords:\n{backend_keywords}")
        return backend_keywords
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating title: {str(e)}")

async def generate_amazon_description():
    try:
        """Generates an SEO-optimized Amazon product description."""
        if not product_url:
            return "Failed to generate product description: No product data found"
        response = await asyncio.to_thread(client.chat.completions.create,
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": description_prompt}]
        )
        
        optimized_description = response.choices[0].message.content.strip()
        print("Generated Amazon Product Description")
        append_to_google_doc(DOCUMENT_ID, f"Amazon Product Description:\n{optimized_description}")
        return optimized_description
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating title: {str(e)}")

credentials_file = "google-credentials.json"
amazon_sheet_url = "https://docs.google.com/spreadsheets/d/1A3SW1gqTQrB0Z5jGm0PcNQJnw2IcGFHuZd1aRPLt8ZQ/edit"
scrap_sheet_url = "https://docs.google.com/spreadsheets/d/18UoIYMIzRXZzsWX12oTsEk13W3jTA9oTd_kT-iSQb4c/edit"
output_sheet_url = "https://docs.google.com/spreadsheets/d/1At_QcMag0-jsEhoyMhhAPb1e_uUO26p56s9hX9-81rk/edit"
product_url = "https://www.naturesustained.com/products/natural-shampoo?variant=44673198489761"

title_prompt = f"""
    Act like an Amazon SEO expert specializing in the industry with 10+ years of experience.
    Your goal is to create a 100% optimized, keyword-rich, and compelling SEO title for a product listing
    that maximizes visibility and click-through rate (CTR) on Amazon.

    Instructions:
    - Analyze Audience & Platform: Optimize the title for Amazon shoppers, balancing readability and SEO.
    - Keywords & Relevance: Include high-volume keywords from the "Keyword Doc" naturally.
    - Optimization for Click-Through: Prioritize readability, use title casing, and limit to 200 characters.
    - Unique Selling Points (USP): Highlight 1-2 differentiators (e.g., “Eco-Friendly,” “Fast-Absorbing”).
    - Repetition: Titles must not contain the same word more than twice.

    Generate an Amazon-style product title for the following product description:
    {product_url}
    """
bullets_prompt = f"""
    Act as an Amazon SEO expert and high-converting content writer specializing in this industry. With 10+ years of experience, your objective is to craft five compelling, SEO-optimized bullet points for an Amazon product listing. These bullet points should effectively highlight key features, emphasize benefits, and incorporate high-impact keywords to enhance customer engagement, readability, and discoverability. The ultimate goal is to maximize conversion rate (CVR) and drive sales.

    Instructions:
    1. Identify & Highlight Key Features  
    - Extract the most compelling product features from the provided description and focus each bullet point on a distinct feature.  
    - Showcase how each feature addresses customer needs, solves pain points, or enhances the user experience.  
    - Use persuasive, benefit-driven language that resonates with the target audience.  

    2. Integrate High-Impact Keywords Naturally  
    - Utilize highly relevant, high-search-volume keywords from Amazon search trends without keyword stuffing.  
    - Maintain natural readability while optimizing for search rankings, ensuring compliance with Amazon’s guidelines.  

    3. Prioritize Benefits Over Features  
    - Transform technical features into customer-centric benefits.  
    - Example: Instead of “Waterproof Design,” write “WATERPROOF DESIGN: Stay dry in any weather with a fully waterproof build, ideal for outdoor adventures.”  

    4. Structure for Readability & Engagement  
    - Format: Start each bullet point with a capitalized key feature for clarity (e.g., "PREMIUM MATERIAL: …").  
    - Tone: Maintain a professional, engaging, and persuasive style.  
    - Flow: Ensure a logical progression across the five points, covering unique aspects without redundancy.  

    5. Character Limit & Formatting  
    - Keep each bullet point within 200 characters for optimal readability.  
    - Ensure content is concise, scannable, and easy to understand at a glance.  

    Take a deep breath and approach this step-by-step, ensuring each bullet point is optimized for impact, clarity, and conversion.

    ### **Product Information:**
    {product_url}
    """
keywords_prompt = f"""
    Act as an Amazon SEO expert. Generate a **single** backend keyword string (100 characters max) that maximizes discoverability while strictly following Amazon’s guidelines.

    **Instructions:**
    **Extract Unique, High-Relevance Keywords**
    - Use only high-converting, relevant keywords from the “Keyword Doc”
    - Use the “URLs” to learn about the product to choose 100% relevant keywords.
    - Remove duplicate or closely related terms (e.g., exclude both "organic shampoo" and "shampoo organic").

    **Follow Amazon’s Backend Keyword Policies**
    ✅ No Commas – Separate keywords with spaces for full character efficiency.
    ✅ No Competitor Brand Names, ASINs, or Promotional Claims (e.g., avoid “best shampoo,” “top-rated”).
    ✅ No Redundant or Overlapping Keywords (e.g., avoid using both "dandruff shampoo" and "anti-dandruff shampoo").

    **Prioritize Broad Discoverability & Conversion Potential**
    - Include synonyms, regional spellings, and related terms customers might search for.
    - Cover different customer pain points (e.g., “itchy scalp relief,” “hair regrowth”).
    - Expand with related but distinct keywords that increase exposure across multiple search queries.

    **Utilize STRICTLY 100 CHARACTERS Limit Without Wasting Space**
    - Include product variations, use cases, and relevant attributes (e.g., size, material, color, features).
    - Include problem-solution keywords (hydrating, clarifying, scalp care).
    - Use alternative terms and phrasing for broader search inclusion.


    **Instructions:**
    - Extract only high-converting, relevant keywords from the product page.
    - No commas, separate keywords with spaces.
    - No competitor brand names, ASINs, or promotional claims.
    - No redundant or overlapping keywords.
    - Utilize synonyms, regional spellings, and alternative terms.
    - Prioritize broad discoverability & conversion potential.
    - Ensure the final output is exactly **100 characters** long.
    
    **Product Information:**
    {product_url}
    """

description_prompt = f"""
    Act as an Amazon copywriting expert with 10+ years of experience crafting high-converting, SEO-optimized product descriptions 
    that enhance product visibility and drive sales. Your goal is to create a clear, engaging, and persuasive product description 
    that highlights the product’s unique features and key benefits while seamlessly integrating relevant keywords to improve search rankings and sales volumes.
    
    Step 1: Research the Product from URLs:
    - Extract all relevant product information from the provided URLs.
    - Identify key features, benefits, materials, specifications, and unique selling points.
    - Understand the target audience and intended use cases.
    - Note any customer reviews or feedback to identify common pain points or standout benefits.
    
    Step 2: Write the Product Description:
    - **Engaging Introduction**: Begin with a compelling hook that immediately grabs the reader’s attention.
    - Clearly define the product’s primary purpose and the key problem it solves.
    - Use powerful adjectives and action-driven language to make it emotionally appealing.
    
    - **Key Features & Benefits**: List each feature concisely, followed by a short, benefit-driven explanation.
    - Prioritize clarity, avoiding jargon while maintaining a professional and trustworthy tone.
    - Integrate relevant Amazon SEO keywords naturally for better visibility from the “Keyword Doc.”
    
    - **Unique Selling Points**: Emphasize 1-2 standout features that set this product apart from competitors.
    - Highlight any special materials, advanced technology, or unique design elements.
    - Use persuasive language to make these points memorable.
    
    - **Usage & Versatility**: Explain who the product is ideal for (e.g., busy professionals, parents, athletes, kids).
    - Mention multiple use cases or settings where this product excels.
    - Provide reassurance on ease of use, durability, or effectiveness.
    
    - **Final Format**: Aim for 150-200 words in a friendly, persuasive tone and write it all in **one paragraph**.
    
    Product Information:
    {product_url}
    """

client = openai.OpenAI(api_key=api_key)


# match_and_create_google_sheet(credentials_file, amazon_sheet_url, scrap_sheet_url, output_sheet_url, product_url)
# generate_amazon_backend_keywords()
# generate_amazon_bullets()
# generate_amazon_description()
# generate_amazon_title()
