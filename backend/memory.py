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

def save_playbook_rule(domain: str, rule: str, client_id: str = None, goal: str = None):
    """Saves a playbook rule for a specific domain and goal to the vector database."""
    if not playbook_collection:
        print("ChromaDB not initialized, cannot save rule.")
        return

    try:
        # We use a deterministic hash of the rule as the ID
        rule_hash = hashlib.sha256(rule.encode()).hexdigest()

        doc_id = f"{domain}_{client_id}_{rule_hash}" if client_id else f"{domain}_{rule_hash}"

        metadata = {"domain": domain}
        if client_id:
            metadata["client_id"] = client_id
        if goal:
            metadata["goal"] = goal

        playbook_collection.upsert(
            documents=[rule],
            metadatas=[metadata],
            ids=[doc_id]
        )
        print(f"Saved playbook rule for {domain} (client: {client_id}): {rule}")
    except Exception as e:
        print(f"Error saving playbook rule: {e}")

def get_playbook_rules(domain: str, query: str = "", n_results: int = 3, client_id: str = None, goal: str = None) -> List[str]:
    """Retrieves relevant playbook rules for a domain and an optional goal."""
    if not playbook_collection:
        print("ChromaDB not initialized, cannot retrieve rules.")
        return []

    try:
        # We prioritize the goal in the search query for contextual retrieval
        search_query = goal if goal else (query if query else f"Rules for {domain}")

        where_clause = {"domain": domain}
        try:
            if client_id:
                # ChromaDB's local format doesn't natively support $exists: False perfectly in all versions without a proper index or type.
                # A safer approach is to query twice if we want both, or do client_id specific first.
                # Since Chroma's metadata filtering is sometimes limited on missing fields, let's do two queries.

                # Query 1: Client specific
                client_results = playbook_collection.query(
                    query_texts=[search_query],
                    n_results=n_results,
                    where={"$and": [{"domain": domain}, {"client_id": client_id}]}
                )

                # Query 2: General domain
                general_results = playbook_collection.query(
                    query_texts=[search_query],
                    n_results=n_results,
                    where={"domain": domain}
                )

                all_rules = []

                if client_results and client_results.get("documents"):
                    for doc_list in client_results["documents"]:
                        for doc in doc_list:
                            if doc not in all_rules:
                                all_rules.append(doc)

                if general_results and general_results.get("documents") and general_results.get("metadatas"):
                    for doc_list, meta_list in zip(general_results["documents"], general_results["metadatas"]):
                        for doc, meta in zip(doc_list, meta_list):
                            # Ensure it's a general rule (no client_id)
                            if "client_id" not in meta and doc not in all_rules:
                                all_rules.append(doc)
                return all_rules
            else:
                results = playbook_collection.query(
                    query_texts=[search_query],
                    n_results=n_results,
                    where={"domain": domain}
                )
                if results and results.get("documents") and len(results["documents"]) > 0:
                    all_rules = []
                    for doc_list in results["documents"]:
                        for doc in doc_list:
                            all_rules.append(doc)
                    return all_rules
                return []
        except Exception as filter_e:
            print(f"Warning: ChromaDB advanced filter failed, falling back to simple query: {filter_e}")
            results = playbook_collection.query(
                query_texts=[search_query],
                n_results=n_results,
                where={"domain": domain}
            )
            if results and results.get("documents") and len(results["documents"]) > 0:
                all_rules = []
                for doc_list in results["documents"]:
                    for doc in doc_list:
                        all_rules.append(doc)
                return all_rules
            return []


    except Exception as e:
        print(f"Error retrieving playbook rules: {e}")
        return []
