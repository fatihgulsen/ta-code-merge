# Synonyms Data Directory

Bu dizin, 65 farklı ülkeye ait firma unvan suffix'lerini, yasal kelimeleri, makaleleri (articles/stopwords) ve sektör bazlı eş anlamlı kelimeleri barındıran JSON dosyalarını içerir.

---

## 1. Veri Yapısı (JSON Structure)

Her ülke JSON dosyası aşağıdaki 4 ana kategoride kelime listeleri içerir:

```json
{
  "legal_suffix": [
    "co. ltd.",
    "incorporated",
    "corp"
  ],
  "address_keyword": [
    "floor",
    "street",
    "plaza"
  ],
  "articles": [
    "the",
    "and",
    "of"
  ],
  "business_sector": [
    "trading",
    "logistics",
    "construction"
  ]
}
```

*   **`legal_suffix`**: Firma tiplerini belirten ve normalize edilmesi gereken suffix'ler (A.Ş., Ltd, GmbH).
*   **`address_keyword`**: Şirket adlarında yanlışlıkla yer alan adres sızıntılarını kesmek için kullanılan anchor kelimeler.
*   **`articles`**: Eşleşmelerde göz ardı edilebilecek veya düşük ağırlıklı stopwords listeleri.
*   **`business_sector`**: Şirketlerin faaliyet sektörlerini belirten ve canonical forma çevrilen anahtar kelimeler.

---

## 2. SYNONYM GÜNCELLEME KURALLARI (IMMUTABILITY POLICY)

> [!CAUTION]
> **BU DİZİNDEKİ JSON DOSYALARI TAMAMEN SABİTTİR (IMMUTABLE).**
> Dosyaların içindeki orijinal kelimeleri doğrudan silmek, değiştirmek veya değiştirmesini beklemek sistemin geriye dönük tutarlılığını (baseline) bozar.

### Eğer bir typo veya eşleşme hatası düzeltilmek isteniyorsa:
1.  **`config.py` kullanın**: `config.py` içerisine yeni suffix typo haritaları (`SUFFIX_TYPO_MAP`) veya genel synonym override'ları ekleyin.
2.  **ES Index Rebuild edin**: Yeni synonym kurallarının veya config ayarlarının ES tarafına yansıması için index'i yeniden oluşturun:
    ```bash
    python es_manager.py --force
    ```
