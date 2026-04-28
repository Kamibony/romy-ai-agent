import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import os
import hashlib
from datetime import datetime, timezone
import chromadb
from firebase_admin import firestore

class AbstractMemoryRepository(ABC):
    @abstractmethod
    def save_playbook_rule(self, domain: str, rule: str, client_id: Optional[str] = None, goal: Optional[str] = None, source: str = "synthesizer") -> None:
        pass

    @abstractmethod
    def delete_playbook_rule(self, doc_id: str, client_id: Optional[str] = None) -> bool:
        pass

    @abstractmethod
    def list_playbook_rules(self, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_playbook_rules(self, domain: str, query: str = "", n_results: int = 3, client_id: Optional[str] = None, goal: Optional[str] = None) -> List[str]:
        pass

class FirestoreMemoryRepository(AbstractMemoryRepository):
    def __init__(self):
        # Initialize ChromaDB locally
        CHROMA_DB_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
        os.makedirs(CHROMA_DB_DIR, exist_ok=True)

        try:
            self.chroma_client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
            self.playbook_collection = self.chroma_client.get_or_create_collection(name="site_playbooks")
        except Exception as e:
            logging.info(f"Failed to initialize ChromaDB: {e}")
            self.chroma_client = None
            self.playbook_collection = None

    def save_playbook_rule(self, domain: str, rule: str, client_id: Optional[str] = None, goal: Optional[str] = None, source: str = "synthesizer") -> None:
        # 1. Generate Deterministic ID
        try:
            if goal:
                goal_hash = hashlib.sha256(goal.encode()).hexdigest()
                doc_id = f"{domain}_{client_id}_{goal_hash}" if client_id else f"{domain}_{goal_hash}"
            else:
                rule_hash = hashlib.sha256(rule.encode()).hexdigest()
                doc_id = f"{domain}_{client_id}_{rule_hash}" if client_id else f"{domain}_{rule_hash}"
        except Exception as e:
            logging.info(f"Error generating ID for playbook rule: {e}")
            return

        # 2. Write to ChromaDB (for vector search)
        if self.playbook_collection:
            try:
                metadata = {"domain": domain}
                if client_id:
                    metadata["client_id"] = client_id
                if goal:
                    metadata["goal"] = goal

                self.playbook_collection.upsert(
                    documents=[rule],
                    metadatas=[metadata],
                    ids=[doc_id]
                )
                logging.info(f"Saved playbook rule to ChromaDB for {domain} (client: {client_id}): {rule}")
            except Exception as e:
                logging.info(f"Error saving playbook rule to ChromaDB: {e}")
        else:
            logging.info("ChromaDB not initialized, skipping ChromaDB save.")

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
            logging.info(f"Saved playbook rule to Firestore (client: {client_id}, doc_id: {doc_id})")
        except Exception as e:
            logging.info(f"Error saving playbook rule to Firestore: {e}")

    def delete_playbook_rule(self, doc_id: str, client_id: Optional[str] = None) -> bool:
        success = True

        # 1. Delete from ChromaDB
        if self.playbook_collection:
            try:
                self.playbook_collection.delete(ids=[doc_id])
                logging.info(f"Deleted playbook rule {doc_id} from ChromaDB")
            except Exception as e:
                logging.info(f"Error deleting playbook rule {doc_id} from ChromaDB: {e}")
                success = False

        # 2. Delete from Firestore
        try:
            db = firestore.client()
            if client_id:
                db.collection("tenants").document(client_id).collection("memory_rules").document(doc_id).delete()
            else:
                db.collection("global_memory_rules").document(doc_id).delete()
            logging.info(f"Deleted playbook rule {doc_id} from Firestore")
        except Exception as e:
            logging.info(f"Error deleting playbook rule {doc_id} from Firestore: {e}")
            success = False

        return success

    def list_playbook_rules(self, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
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
            logging.info(f"Error listing playbook rules from Firestore: {e}")
            return []

    def get_playbook_rules(self, domain: str, query: str = "", n_results: int = 3, client_id: Optional[str] = None, goal: Optional[str] = None) -> List[str]:
        if not self.playbook_collection:
            logging.info("ChromaDB not initialized, cannot retrieve rules.")
            return []

        try:
            # We prioritize the goal in the search query for contextual retrieval
            search_query = goal if goal else (query if query else f"Rules for {domain}")

            where_clause = {"domain": domain}
            try:
                if client_id:
                    # Query 1: Client specific
                    client_results = self.playbook_collection.query(
                        query_texts=[search_query],
                        n_results=n_results,
                        where={"$and": [{"domain": domain}, {"client_id": client_id}]}
                    )

                    # Query 2: General domain
                    general_results = self.playbook_collection.query(
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
                                if "client_id" not in meta and doc not in all_rules:
                                    all_rules.append(doc)
                    return all_rules
                else:
                    results = self.playbook_collection.query(
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
                logging.info(f"Warning: ChromaDB advanced filter failed, falling back to simple query: {filter_e}")
                results = self.playbook_collection.query(
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
            logging.info(f"Error retrieving playbook rules: {e}")
            return []

class InMemoryMemoryRepository(AbstractMemoryRepository):
    def __init__(self):
        self.rules: Dict[str, Dict[str, Any]] = {}

    def save_playbook_rule(self, domain: str, rule: str, client_id: Optional[str] = None, goal: Optional[str] = None, source: str = "synthesizer") -> None:
        try:
            if goal:
                goal_hash = hashlib.sha256(goal.encode()).hexdigest()
                doc_id = f"{domain}_{client_id}_{goal_hash}" if client_id else f"{domain}_{goal_hash}"
            else:
                rule_hash = hashlib.sha256(rule.encode()).hexdigest()
                doc_id = f"{domain}_{client_id}_{rule_hash}" if client_id else f"{domain}_{rule_hash}"
        except Exception as e:
            logging.info(f"Error generating ID for playbook rule: {e}")
            return

        payload = {
            "id": doc_id,
            "domain": domain,
            "rule": rule,
            "goal": goal,
            "source": source,
            "updated_at": datetime.now(timezone.utc),
            "success_rate": 1.0,
            "success_count": 0,
            "fail_count": 0,
            "client_id": client_id
        }
        self.rules[doc_id] = payload
        logging.info(f"[InMemory] Saved playbook rule (client: {client_id}, doc_id: {doc_id})")

    def delete_playbook_rule(self, doc_id: str, client_id: Optional[str] = None) -> bool:
        if doc_id in self.rules:
            rule = self.rules[doc_id]
            if client_id and rule.get("client_id") != client_id:
                return False
            del self.rules[doc_id]
            logging.info(f"[InMemory] Deleted playbook rule {doc_id}")
            return True
        return False

    def list_playbook_rules(self, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if client_id:
            return [rule for rule in self.rules.values() if rule.get("client_id") == client_id]
        else:
            return [rule for rule in self.rules.values() if rule.get("client_id") is None]

    def get_playbook_rules(self, domain: str, query: str = "", n_results: int = 3, client_id: Optional[str] = None, goal: Optional[str] = None) -> List[str]:
        matching_rules = []
        for doc_id, rule_data in self.rules.items():
            if rule_data.get("domain") == domain:
                if client_id:
                    # Match specific client or general
                    if rule_data.get("client_id") == client_id or rule_data.get("client_id") is None:
                        matching_rules.append(rule_data.get("rule"))
                else:
                    if rule_data.get("client_id") is None:
                        matching_rules.append(rule_data.get("rule"))

        return matching_rules[:n_results]

# Dependency Provider
_in_memory_repo = None
_firestore_repo = None

def get_memory_repository() -> AbstractMemoryRepository:
    global _in_memory_repo, _firestore_repo
    is_local = os.environ.get("LOCAL_DEV") == "True" or os.environ.get("ROMY_TEST_MODE") == "1"

    if is_local:
        if _in_memory_repo is None:
            _in_memory_repo = InMemoryMemoryRepository()
        return _in_memory_repo
    else:
        if _firestore_repo is None:
            _firestore_repo = FirestoreMemoryRepository()
        return _firestore_repo
