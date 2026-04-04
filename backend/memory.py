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

from firebase_admin import firestore
from datetime import datetime, timezone

def save_playbook_rule(domain: str, rule: str, client_id: str = None, goal: str = None, source: str = "synthesizer"):
    """Saves a playbook rule using a dual-write architecture to both ChromaDB and Firestore."""

    # 1. Generate Deterministic ID
    try:
        if goal:
            goal_hash = hashlib.sha256(goal.encode()).hexdigest()
            doc_id = f"{domain}_{client_id}_{goal_hash}" if client_id else f"{domain}_{goal_hash}"
        else:
            rule_hash = hashlib.sha256(rule.encode()).hexdigest()
            doc_id = f"{domain}_{client_id}_{rule_hash}" if client_id else f"{domain}_{rule_hash}"
    except Exception as e:
        print(f"Error generating ID for playbook rule: {e}")
        return

    # 2. Write to ChromaDB (for vector search)
    if playbook_collection:
        try:
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
            print(f"Saved playbook rule to ChromaDB for {domain} (client: {client_id}): {rule}")
        except Exception as e:
            print(f"Error saving playbook rule to ChromaDB: {e}")
    else:
        print("ChromaDB not initialized, skipping ChromaDB save.")

    # 3. Write to Firestore (for Dashboard UI & CRUD)
    try:
        db = firestore.client()

        # We structure this by tenant if client_id is present, otherwise in a global collection
        payload = {
            "id": doc_id,
            "domain": domain,
            "rule": rule,
            "goal": goal,
            "source": source,
            "updated_at": datetime.now(timezone.utc),
            "success_rate": 1.0, # Initial success rate
            "success_count": 0,
            "fail_count": 0
        }

        if client_id:
            payload["client_id"] = client_id
            collection_ref = db.collection("tenants").document(client_id).collection("memory_rules")
        else:
            collection_ref = db.collection("global_memory_rules")

        collection_ref.document(doc_id).set(payload, merge=True)
        print(f"Saved playbook rule to Firestore (client: {client_id}, doc_id: {doc_id})")
    except Exception as e:
        print(f"Error saving playbook rule to Firestore: {e}")

def delete_playbook_rule(doc_id: str, client_id: str = None) -> bool:
    """Deletes a playbook rule from both ChromaDB and Firestore."""
    success = True

    # 1. Delete from ChromaDB
    if playbook_collection:
        try:
            playbook_collection.delete(ids=[doc_id])
            print(f"Deleted playbook rule {doc_id} from ChromaDB")
        except Exception as e:
            print(f"Error deleting playbook rule {doc_id} from ChromaDB: {e}")
            success = False

    # 2. Delete from Firestore
    try:
        db = firestore.client()
        if client_id:
            db.collection("tenants").document(client_id).collection("memory_rules").document(doc_id).delete()
        else:
            db.collection("global_memory_rules").document(doc_id).delete()
        print(f"Deleted playbook rule {doc_id} from Firestore")
    except Exception as e:
        print(f"Error deleting playbook rule {doc_id} from Firestore: {e}")
        success = False

    return success

def list_playbook_rules_from_firestore(client_id: str = None):
    """Lists playbook rules from Firestore (fast, no vector search)."""
    try:
        db = firestore.client()
        rules = []
        if client_id:
            docs = db.collection("tenants").document(client_id).collection("memory_rules").stream()
        else:
            docs = db.collection("global_memory_rules").stream()

        for doc in docs:
            rule_data = doc.to_dict()
            rule_data["id"] = doc.id
            rules.append(rule_data)
        return rules
    except Exception as e:
        print(f"Error listing playbook rules from Firestore: {e}")
        return []

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
