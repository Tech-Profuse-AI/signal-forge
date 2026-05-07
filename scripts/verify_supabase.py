import os
import sys
from pprint import pprint
import json

# Ensure SignalForge is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.settings import Settings
from storage.supabase_store import get_supabase_client_from_settings, SupabaseTableStore

def verify_tables():
    settings = Settings()
    client = get_supabase_client_from_settings(settings)
    
    if not client.is_configured():
        print("Supabase is not configured.")
        return
        
    print(f"Supabase configured: {client.url}")
    print(f"Supabase ping successful: {client.ping()}")
    
    tables = [
        ("review_queue", "review_id"),
        ("analytics_events", "event_id"),
        ("learning_state", "id"),
        ("scheduled_tasks", "id"),
    ]
    
    results = {}
    
    for table_name, pk in tables:
        store = SupabaseTableStore(client=client, table=table_name, primary_key=pk)
        try:
            rows = store.load()
            results[table_name] = {
                "success": True,
                "count": len(rows),
                "sample": rows[0] if rows else None
            }
        except Exception as e:
            results[table_name] = {
                "success": False,
                "error": str(e),
                "count": 0,
                "sample": None
            }
            
    print("\n" + "="*50)
    print("SUPABASE PERSISTENCE VERIFICATION")
    print("="*50)
    
    for table_name, data in results.items():
        print(f"\n--- Table: {table_name} ---")
        if data["success"]:
            print(f"Rows found: {data['count']}")
            if data["sample"]:
                print("Sample Row (Keys):", list(data["sample"].keys()))
                
                # Verify JSONB payload
                if "record" in data["sample"]:
                    record_type = type(data["sample"]["record"]).__name__
                    is_dict = isinstance(data["sample"]["record"], dict)
                    print(f"JSONB 'record' payload stored correctly: {is_dict} (type: {record_type})")
                else:
                    print(f"JSONB 'record' payload stored correctly: N/A (Not applicable for this schema)")
                    
                print("\nSample Row Data:")
                pprint(data["sample"], depth=2)
            else:
                print("No rows found. Validating if this is expected...")
                
        else:
            print(f"FAIL - Exact Supabase error: {data['error']}")
            
if __name__ == "__main__":
    verify_tables()
