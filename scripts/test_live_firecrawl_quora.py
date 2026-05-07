import os
import sys
from pprint import pprint

# Ensure SignalForge is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
from providers.quora_provider import QuoraProvider
import logging

logging.basicConfig(level=logging.INFO)

def main():
    load_dotenv()
    
    if not os.environ.get("FIRECRAWL_API_KEY"):
        print("ERROR: FIRECRAWL_API_KEY is missing from environment")
        return

    provider = QuoraProvider(mock_mode=False)
    
    query = "AI automation workflow"
    print(f"Executing search for query: '{query}'")
    
    urls = provider._search_quora_urls(query, limit=1)
    
    if not urls:
        print("Search returned 0 URLs.")
        return
        
    url = urls[0]
    print(f"Found URL: {url}")
    print("Testing Firecrawl direct extraction...")
    
    # Intercept fallback parser to know if it was used
    fallback_called = False
    original_parse = provider._parse_quora_page
    def intercept_parse(u):
        nonlocal fallback_called
        fallback_called = True
        print("\nFirecrawl unavailable, fallback parser used")
        return original_parse(u)
    provider._parse_quora_page = intercept_parse
    
    # Intercept Firecrawl to capture exact error
    scrape_error = None
    original_scrape = provider._firecrawl_scrape
    def intercept_scrape(*args, **kwargs):
        nonlocal scrape_error
        try:
            return original_scrape(*args, **kwargs)
        except Exception as e:
            scrape_error = str(e)
            raise
    provider._firecrawl_scrape = intercept_scrape

    raw = None
    try:
        raw = provider._crawl_quora_page(url)
    except Exception as e:
        print(f"Exception during crawl_quora_page: {e}")
        
    if scrape_error:
        print(f"\nFirecrawl failed: exact failure reason: {scrape_error}")
        
    if not raw:
        # Since _crawl_quora_page failed or returned None, we test the fallback behavior explicitly if we want to mimic fetch_posts
        # but let's just trigger it to fulfill the "If fallback parser is triggered: explicitly print..." requirement
        print("Firecrawl returned None. Triggering fallback...")
        raw = provider._parse_quora_page(url)
        
    if not raw:
        print("Extraction completely failed.")
        return
        
    post = provider.normalize(raw)
    
    print("\n--- Extraction Results ---")
    print("Number of results: 1")
    print("First result sample:")
    pprint(post)
    print(f"\nExtracted title: {post.get('title')}")
    print(f"Score: {post.get('score')}")
    print(f"Author: {post.get('author')}")
    print(f"Body length: {len(post.get('body', ''))}")
    
    print("\nValidating extracted fields...")
    required = ['platform', 'title', 'body', 'score', 'author', 'topic', 'url']
    success = True
    for field in required:
        if field not in post:
            print(f"Validation failed: missing field '{field}'")
            success = False
            
    if success:
        print("Validation passed.")

if __name__ == "__main__":
    main()
