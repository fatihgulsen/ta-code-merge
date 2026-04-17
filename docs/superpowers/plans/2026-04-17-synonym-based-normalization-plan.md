# Synonym-Based Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `es_manager.py`, `es_ingest.py`, and `mx.json` to utilize Elasticsearch native char filters and simplified synonym maps instead of complex code regexes.

**Architecture:** We will add a `punctuation_remover` `char_filter` to Elasticsearch mapping that replaces dots and commas with single spaces. Python ingest logic will remove its heavy suffix/parentheses regex formatting logic. `mx.json` will adopt a cleaner mapping format relying on this char filter.

**Tech Stack:** Python, Elasticsearch Painless, Elasticsearch Mapping API

---

### Task 1: Elasticsearch Analyzer Change

**Files:**
- Modify: `c:\All-project\ta-code-merge\es_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# Create a temporary scratch script: tests/test_analyzer.py
# (We will use this to verify mapping changes)
def test_analyzer_logic():
    # Will be tested manually via print or assertion
    pass
```

- [ ] **Step 2: Write minimal implementation**

Modify `es_manager.py`:
Add the `char_filter` into `build_index_settings()` around line 95, where filters are being set.

```python
    # After line 95...
    filters["arabic_norm"] = {
        "type": "arabic_normalization"
    }
    
    # ADD CHAR FILTER
    char_filters = {
        "punctuation_remover": {
            "type": "pattern_replace",
            "pattern": "[.,]+",
            "replacement": " "
        }
    }

    base_clean_filters = []
    # ...
```
Wait, `char_filter` must be set alongside `filter` in the `analysis` block.
Modify the output of `build_index_settings` at the end (around line 232):

```python
            "analysis": {
                "char_filter": char_filters, # Added this line
                "tokenizer": tokenizers,
                "filter": filters,
                "analyzer": analyzers,
            },
```
Then for each `analyzer` in `analyzers`, add `"char_filter": ["punctuation_remover"]`.
For example:
```python
    analyzers["clean_analyzer_common"] = {
        "tokenizer": "standard",
        "char_filter": ["punctuation_remover"],
        "filter": base_clean_filters + ["synonym_filter_common"],
    }
```
Apply this to `analyzers["stripped_search_analyzer"]`, per-country analyzers, `ngram_analyzer`, `ngram_search_analyzer`, `phonetic_analyzer`, and `icu_analyzer` if present.

- [ ] **Step 3: Run test to verify it passes**

Run: `python c:\All-project\ta-code-merge\es_manager.py`
Expected: Passes without syntax error.

- [ ] **Step 4: Commit**

```bash
git add es_manager.py
git commit -m "feat: add punctuation_remover char_filter to ES mappings"
```

### Task 2: Ingest Pipeline Refactor

**Files:**
- Modify: `c:\All-project\ta-code-merge\es_ingest.py:84-164`

- [ ] **Step 1: Write minimal implementation**

Remove the regex lines 84 to 164 in `es_ingest.py` (parentheses, letter/suffix matching).

```python
# Before (approx line 80):
        # 1. Lowercase
        "  text = text.toLowerCase();",
        # 2. Zero-width karakter temizligi (regex literal ile)
        r"  text = /[\u200b\u200c\u200d\ufeff\u00ad]/.matcher(text).replaceAll('');",

# After the above, only keep HTML label stripping and duplicate space stripping, and add to results.
        # 4. Label temizligi
        r"  text = /^(email|attn|tel|phone|web|site)\s*:/.matcher(text).replaceAll('');",
        r"  text = /\bc\/o\b/.matcher(text).replaceAll('');",
        r"  text = /\battn\b/.matcher(text).replaceAll('');",
        r"  text = /\bcare of\b/.matcher(text).replaceAll('');",
        r"  text = /\bto\s+(the\s+)?order\s+of\b/.matcher(text).replaceAll('');",
        # 5. Ampersand normalizasyonu
        r"  text = /\s*&\s*/.matcher(text).replaceAll(' and ');",
        # 6. Cift bosluk temizligi
        r"  text = /\s+/.matcher(text).replaceAll(' ').trim();",
        # Sonuca ekle
        "  if (text.length() > 0 && !cleanedVariations.contains(text)) {",
        "    cleanedVariations.add(text);",
        "  }",
        "}",
        "ctx.variations = cleanedVariations;",
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python c:\All-project\ta-code-merge\es_ingest.py`
Expected: All pipeline scripts register successfully without Painless syntax errors.

- [ ] **Step 3: Commit**

```bash
git add es_ingest.py
git commit -m "refactor: simplify painless regex formatting script"
```

### Task 3: MX Synonym Format Refactor

**Files:**
- Modify: `c:\All-project\ta-code-merge\synonyms_data\mx.json`

- [ ] **Step 1: Write minimal implementation**

Rewrite `mx.json` entirely. Remove `company_types` and create `legal_suffixes` and `business_sectors` according to `_template.json` standard. Use spaced variations anticipating the char_filter replacing dots.

```json
{
  "legal_suffixes": [
    "sociedad limitada, sl, s l, soc limitada => sl",
    "sociedad limitada unipersonal, slu, s l u => slu",
    "sociedad anonima, sa, s a, soc anonima => sa",
    "sociedad anonima de capital variable, sa de cv, s a de c v, sadecv, s a de cv => sa de cv",
    "sociedad de responsabilidad limitada, srl, s r l, s de rl, s de r l => srl",
    "sociedad de responsabilidad limitada de capital variable, s de rl de cv, s de r l de c v => s de rl de cv",
    "sociedad por acciones simplificada, sas, s a s => sas",
    "sociedad civil, sc, s c => sc",
    "asociacion civil, ac, a c => ac",
    "sociedad cooperativa, s c coop, cooperativa, coop => coop",
    "empresa productiva del estado => empresa productiva del estado",
    "persona fisica => persona fisica",
    "sociedad anonima bursatil, sab, s a b => sab",
    "sociedad anonima promotora de inversion, sapi, s a p i => sapi",
    "sociedad anonima promotora de inversion de capital variable, sapi de cv, s a p i de c v => sapi de cv",
    "sociedad en nombre colectivo => sociedad en nombre colectivo",
    "sociedad en comandita simple => sociedad en comandita simple",
    "sociedad en comandita por acciones, s en c por a, s en c por a => s en c por a",
    "asociacion en participacion, a en p, a en p => a en p",
    "organismo publico descentralizado, opd => opd",
    "compania, cia, => cia",
    "hermanos, hnos => hnos",
    "sucursal, suc => suc"
  ],
  "business_sectors": [
    "empresa => empresa",
    "comercial => comercial",
    "industrial => industrial",
    "internacional, intl, inter => internacional",
    "productores, productos, prod => prod"
  ],
  "articles": [
    "y", "e", "en", "de", "del", "la", "las", "el", "los", "por", "para"
  ],
  "address_terms": [
    "paseo, po, pso => pso",
    "camino, cam, cno => cam",
    "ronda, rda => rda",
    "travesia, trv => trv",
    "via, v => via",
    "carrera, carr, cra => cra",
    "urbanizacion, urb => urb",
    "piso, p, pis, planta => piso",
    "puerta, pta, pto => pta",
    "apartamento, apto, apt, appto => apto",
    "local, loc, lcl => local",
    "bloque, blq, bl => blq",
    "escalera, esc, escal => esc",
    "kilometro, km => km",
    "provincia, prov => prov",
    "region, reg => region",
    "lote, lt => lote",
    "oficina, of, ofic => ofic",
    "street, st, str, calle, c, clle, cl, calzada, calz, callejon => calle",
    "avenue, ave, avenida, av, avda, boulevard, blvrd, blvd, bulevar, blvr => avenida",
    "road, rd, carr, carretera, ctra, crta => carretera",
    "highway, autopista, aut => autopista",
    "alley, andador, and, privada, pas, priv, pasaje, pje, psj => andador",
    "neighborhood, colony, colonia, col, barrio, bo, b, br => colonia",
    "district, distrito => distrito",
    "municipality, municipio, mpio, mun => municipio",
    "state, estado, est, edo => estado",
    "postal code, zip code, codigo postal, cp => codigo postal",
    "cerrada, cda => cerrada",
    "circuito, cto => circuito",
    "periferico, perif => periferico",
    "viaducto, viad => viaducto",
    "retorno, ret => retorno",
    "continuacion, prolongacion, cont, prol => prolongacion",
    "corredor, corr => corredor",
    "plaza, explanada, zocalo, plza, pza, plz, pl => plaza",
    "edificio, edif, ed => edificio",
    "numero exterior, numero, no, num => numero exterior",
    "sin numero, s n, s n => sin numero",
    "departamento, dep, depto, dpto => depto",
    "numero interior, int => numero interior",
    "fraccionamiento, unidad habitacional, residencial, fracc, u h, res => fraccionamiento",
    "pueblo, ejido, rancheria => pueblo",
    "ciudad, cd => ciudad",
    "apartado postal, ap => apartado postal",
    "manzana, mza, mz, manz => mza",
    "ampliacion, ampl => ampliacion"
  ],
  "cities": [
    "mexico city, ciudad de mexico, cdmx, distrito federal, df => ciudad de mexico",
    "guadalajara => guadalajara",
    "monterrey => monterrey",
    "puebla => puebla",
    "tijuana => tijuana",
    "leon => leon",
    "queretaro => queretaro",
    "merida => merida",
    "cancun => cancun",
    "toluca => toluca",
    "chihuahua => chihuahua",
    "hermosillo => hermosillo"
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add synonyms_data/mx.json
git commit -m "feat: restructure mx.json to standard format with whitespace delimiters"
```

### Task 4: Verify Integration

**Files:**
- Create: `c:\All-project\ta-code-merge\verify_analyzer.py`

- [ ] **Step 1: Write test script**

```python
# test_analyzer.py
from es_manager import get_es_client, build_index_settings, create_index
from es_ingest import register_all_pipelines

def verify():
    es = get_es_client()
    create_index(es, force_recreate=True)
    register_all_pipelines(es)
    
    # Analyze text using the common analyzer
    res = es.indices.analyze(
        index="ta_code_merge", 
        body={
            "analyzer": "clean_analyzer_mx",
            "text": "Apex S.A. de C.V. (Mexico Branch)"
        }
    )
    tokens = [t["token"] for t in res["tokens"]]
    print(f"Tokens: {tokens}")
    # Expected: "apex", "sa de cv", "mexico", "branch"

if __name__ == "__main__":
    verify()
```

- [ ] **Step 2: Run test**

Run: `python c:\All-project\ta-code-merge\verify_analyzer.py`

- [ ] **Step 3: Clean up and Commit**

```bash
rm verify_analyzer.py
git commit -m "chore: formatting integration tests successful" --allow-empty
```
