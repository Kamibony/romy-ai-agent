import os
import chromadb
import hashlib
from typing import List

# Initialize ChromaDB locally
CHROMA_DB_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
os.makedirs(CHROMA_DB_DIR, exist_ok=True)

try:
    chroma_client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    playbook_collection = chroma_client.get_or_create_collection(name="site_playbooks")
except Exception as e:
    print(f"Failed to initialize ChromaDB: {e}")
    chroma_client = None
    playbook_collection = None

def save_playbook_rule(domain: str, rule: str):
    """Saves a playbook rule for a specific domain to the vector database."""
    if not playbook_collection:
        print("ChromaDB not initialized, cannot save rule.")
        return

    try:
        # We use a deterministic hash of the rule as the ID
        rule_hash = hashlib.sha256(rule.encode()).hexdigest()
        doc_id = f"{domain}_{rule_hash}"
        playbook_collection.upsert(
            documents=[rule],
            metadatas=[{"domain": domain}],
            ids=[doc_id]
        )
        print(f"Saved playbook rule for {domain}: {rule}")
    except Exception as e:
        print(f"Error saving playbook rule: {e}")

def get_playbook_rules(domain: str, query: str = "", n_results: int = 3) -> List[str]:
    """Retrieves relevant playbook rules for a domain."""
    if not playbook_collection:
        print("ChromaDB not initialized, cannot retrieve rules.")
        return []

    try:
        # Since we just want rules for the domain, we can query with the domain as the text
        # Or if we have a specific task query, we can use that to find the most relevant rules
        search_query = query if query else f"Rules for {domain}"

        results = playbook_collection.query(
            query_texts=[search_query],
            n_results=n_results,
            where={"domain": domain}
        )

        if results and results.get("documents") and len(results["documents"]) > 0:
            return results["documents"][0]
        return []
    except Exception as e:
        print(f"Error retrieving playbook rules: {e}")
        return []
