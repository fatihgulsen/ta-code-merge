# MX Synonyms Typo Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely expand the `mx.json` synonym dictionary to accommodate specific typos in long words and variations of multi-part abbreviations while keeping short standalone tokens strict.

**Architecture:** A targeted JSON expansion directly in the `mx.json` file. The test will run via creating a temporary index in `test_analyzer_index` without impacting the live system.

**Tech Stack:** JSON, Python, Elasticsearch Mapping API.

---

### Task 1: Update the Synonyms (`mx.json`)

**Files:**
- Modify: `synonyms_data/mx.json`

- [ ] **Step 1: Write the updated JSON structure**

We will run a replace of the JSON arrays to inject our calculated variants as detailed in the spec.

- [ ] **Step 2: Commit changes**

```bash
git add synonyms_data/mx.json
git commit -m "feat: vastly expand safe structural typos in mexican synonym dictionary"
```

### Task 2: Build & Run Verification Scripts

**Files:**
- Create: `verify_analyzer.py`

- [ ] **Step 1: Re-create the temp evaluation script**

```python
import sys
from es_manager import get_es_client, build_index_settings

def verify():
    es = get_es_client()
    test_index = "test_analyzer_index"
    
    if es.indices.exists(index=test_index):
        es.indices.delete(index=test_index)
        
    settings = build_index_settings(es)
    
    # We must remove country routing requirement for the test index just to be safe
    if "_routing" in settings["mappings"]:
        del settings["mappings"]["_routing"]
        
    es.indices.create(index=test_index, body=settings)
    
    res = es.indices.analyze(
        index=test_index, 
        body={
            "analyzer": "clean_analyzer_MX",
            "text": "Apex S.A. d C.V. (Mexico Branch)"
        }
    )
    tokens = [t["token"] for t in res["tokens"]]
    print(f"Tokens output for 'Apex S.A. d C.V. (Mexico Branch)': {tokens}")

    es.indices.delete(index=test_index)
    
if __name__ == "__main__":
    verify()
```

- [ ] **Step 2: Run verification mapping**

Run: `python verify_analyzer.py`
Expected: Output successfully lists tokens.

- [ ] **Step 3: Cleanup test file**

Run: `rm verify_analyzer.py`
Run: `git commit -am "chore: expand synonym testing passed"`
