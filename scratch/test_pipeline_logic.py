# scratch/test_pipeline_logic.py
import sys
import os

# Add parent dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from es_queries import NGRAM_MATCH, PHONETIC_MATCH
from config import STAGES
import json

def test_queries():
    print("--- NGRAM_MATCH (Refined) ---")
    q_ngram = NGRAM_MATCH("ALFONSO REYES OCHOA", "MX")
    print(json.dumps(q_ngram, indent=2))
    
    # Verify minimum_should_match is present
    match_clause = q_ngram["query"]["bool"]["must"][0]["match"]["variations_stripped.ngram"]
    assert match_clause["minimum_should_match"] == "75%"
    print("Check: minimum_should_match set to 75% OK")

    print("\n--- PHONETIC_MATCH (New) ---")
    q_phonetic = PHONETIC_MATCH("Gemini Limited", "TR")
    print(json.dumps(q_phonetic, indent=2))
    
    # Verify it uses variations_stripped.phonetic
    assert "variations_stripped.phonetic" in q_phonetic["query"]["bool"]["must"][0]["match"]
    print("Check: phonetic field usage (stripped) OK")

    print("\n--- STAGE ORDER CHECK ---")
    active_stages = sorted(
        [s for s in STAGES if s["enabled"]],
        key=lambda s: s["order"],
    )
    for s in active_stages:
        print(f"Order {s['order']}: {s['name']} (min_score: {s['min_score']})")

    # Verify FUZZY_PHRASE comes before TOKEN_COVERAGE
    phrase_order = next(s["order"] for s in STAGES if s["name"] == "FUZZY_PHRASE")
    token_order = next(s["order"] for s in STAGES if s["name"] == "TOKEN_COVERAGE")
    assert phrase_order < token_order
    print("Check: FUZZY_PHRASE > TOKEN_COVERAGE ordering OK")

if __name__ == "__main__":
    test_queries()
