# Kumluca DWG ↔ Excel doğrulama hedefi (%1)

Bu dosya, **çıktının yalnızca DWG’den** üretildiği ve **`kumluca kaba.xlsx`** ile satır/toplamların **en fazla ~%1 göreli sapma** ile örtüşmesi hedefi için teknik yol haritasıdır.

## Bağlam

- **GT (referans):** `ornekRef/kumluca kaba.xlsx` — karşılaştırma ve metrikler için okunur; çıktı kaynağı değildir.
- **Ölçüm:** Kapalı polylineler, kat planı kümeleme, `calculate()` ile KALIP / BETON satırları.
- **Başarı ölçütü:** `validation_tolerance` (varsayılan `0.01`) altında `compare_reports_full` uyarılarının minimize edilmesi; pratikte satır bazında **max göreli sapma ≤ %1**.

## Faz 0 — Ölçüm ve kıyasın doğru olması

| Görev | Açıklama |
|-------|-----------|
| **Aynı anahtara düşen satırları toplama** | Referans Excel’de (ve bazen hesapta) aynı mantıksal satırın birden çok satırda gelmesi; `comparison_key` ile birleştirilirken **toplam `.total`** kullanılmalı (son satırı saklamak sapmayı çarpıtır). → `gt_io` içinde toplanmış anahtar haritası. |
| **Kot / yazım takma adları** | `comparison_key` + `KUMLUCA_DEFAULT_COMPARE_ALIASES` (ör. `2,85` ↔ `3,00`). Eksik eşlemeler için `comparison_label_aliases` ile YAML genişletmesi. |

## Faz 1 — Kolon kalıp metrajı ve GT notasyonu

Kumluca örneğinde referans kolon kalıp satırındaki **qty1**, çizimden çıkan **tam poligon çevresinin yaklaşık yarısı** ile uyumludur (etkin kalıp şeridi / iki yüz pratiği). Bunun için:

- `CalcParams.column_formwork_strip_fraction` (varsayılan `1.0`; Kumluca için `0.5`).
- Beton hacmi için kesit alanı × yükseklik ayrı doğrulanır (kesit çift sayımı varsa geometri tarafında düzeltilir).

## Faz 2 — Geometri çift sayımı ve döşeme / kiriş *(uygulama)*

| Görev | Durum |
|-------|--------|
| Döşeme net alanında **ortüşen slab birleşimi** (`unary_union` kesit) | `calculator.py` içinde uygulandı |
| Kolon / perde **beton kesit çarpanı** (`column_concrete_section_fraction`, `shear_wall_concrete_section_fraction`) | `CalcParams` + `kumluca.yaml` `0.5` |
| Kiris **kalip uzunluk** + beton kesit carpanlari | `beam_formwork_length_fraction`, `beam_concrete_section_fraction` |
| Radye / doseme alan | `foundation_concrete_section_fraction`, `slab_net_area_fraction` |
| Kiris **IoU dedupe** | `deduplicate_overlapping_beams` → pipeline |

Kalan: parapet etiketleri, satır adları ve tam GT taksonomisi (`comparison_label_aliases`).

## Faz 3 — Etiket ve satır taksonomisi

Referans Excel satır adları (ör. genel kot önekli olmayan satırlar) ile hesap satırları birebir olmayabilir; çözüm sırası:

1. `comparison_label_aliases` ile haritalama.
2. Gerekirse `excel_writer` üretilen etiket biçiminin GT’ye yaklaştırılması (ölçüm formülü değişmeden).

## Faz 4 — Sürekli doğrulama

- CLI / CI: `run --mode structural --structural-config metraj/config/references/kumluca.yaml` ve `dogrulama_ozeti.txt` eşik kontrolü.
- İsteğe bağlı: max rel sapma için pytest eşiği.

---

**Uygulama sırası (bu repoda):** Faz 0–2’nin temel parçaları kodlandı; Faz 3–4 iyileştirmeleri DWG’ye ve projeye göre iteratif devam eder.
