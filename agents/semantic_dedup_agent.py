import logging
import numpy as np
from typing import List, Dict, Any
from providers.vector_store import LocalChromaVectorStore

logger = logging.getLogger(__name__)

class SemanticDedupAgent:
    def __init__(self):
        self.vector_store = LocalChromaVectorStore()
        self.threshold = 0.85

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        vec1, vec2 = np.array(v1), np.array(v2)
        if np.linalg.norm(vec1) == 0 or np.linalg.norm(vec2) == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))

    def _get_safe_embedding(self, text: str) -> List[float]:
        """Safely fetch embedding checking common API patterns, returning empty list on failure."""
        try:
            if hasattr(self.vector_store, 'get_embedding'):
                return self.vector_store.get_embedding(text)
            elif hasattr(self.vector_store, 'embedding_function'):
                return self.vector_store.embedding_function.embed_query(text)
            elif hasattr(self.vector_store, 'embeddings'):
                return self.vector_store.embeddings.embed_query(text)
            else:
                logger.warning("VectorStore lacks a recognizable embedding method.")
                return []
        except Exception as e:
            logger.error(f"Embedding failure during deduplication: {e}")
            return []

    def find_duplicates(self, opportunities: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        # Sort opportunities by score descending to prioritize high-value hits
        sorted_opps = sorted(opportunities, key=lambda x: x.get('score', 0), reverse=True)
        
        kept = []
        kept_embeddings = []  # Side map to prevent mutating the source dictionaries
        duplicates = []

        for opp in sorted_opps:
            text_block = f"{opp.get('title', '')} {opp.get('body', '')}"
            emb = self._get_safe_embedding(text_block)
            
            # Fallback handling: Safe numpy array check
            if emb is None or len(emb) == 0:
                kept.append(dict(opp))  # Polish: Protect upstream references from mutation
                kept_embeddings.append(None)
                continue

            is_duplicate = False
            for j, kept_opp in enumerate(kept):
                kept_emb = kept_embeddings[j]
                
                if kept_emb is None or len(kept_emb) == 0:
                    continue  # Cannot compare against an item that failed embedding

                sim_score = self._cosine_similarity(emb, kept_emb)
                
                if sim_score >= self.threshold:
                    is_duplicate = True
                    print(f"Similarity {sim_score:.2f}: '{opp.get('title')}' mapped to '{kept_opp.get('title')}'")
                    
                    # Preserve metadata from the dropped duplicate
                    if 'duplicate_sources' not in kept_opp:
                        kept_opp['duplicate_sources'] = []
                    
                    kept_opp['duplicate_sources'].append({
                        'id': opp.get('id'),
                        'platform': opp.get('platform', 'unknown'),
                        'url': opp.get('url')
                    })
                    break
            
            if is_duplicate:
                duplicates.append(opp)
            else:
                kept.append(dict(opp))  # Polish: Protect upstream references from mutation
                kept_embeddings.append(emb)

        print(f"Duplicates found: {len(duplicates)}")
        print(f"Kept count: {len(kept)}")
        print(f"Dropped count: {len(duplicates)}")

        return {
            "kept": kept,
            "duplicates": duplicates
        }

    def deduplicate(self, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = self.find_duplicates(opportunities)
        return result["kept"]