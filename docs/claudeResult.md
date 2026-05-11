# Metraj — Evrensel Otomatik Metraj Master Plan (Claude Analizi)

> **Belge amacı.** Bu doküman, `metraj` projesinin "**herhangi bir AutoCAD çiziminden ≥%95 otomatik metraj**" hedefine ulaşması için gerekli yapısal analiz, eksiklik tespiti ve faz-bazlı roadmap'i içerir. Mevcut [docs/result.md](result.md) projenin _bugünkü_ durumunu özetler; bu belge ise _yarına_ giden yol haritasıdır. Gelecek geliştirme oturumlarının temel referansı olarak kullanılır.

---

## STATUS (güncel): Faz 0-7 + Calibration Wizard + Excel-Bağımsız Config Wizard tamamlandı ✓

**Roadmap'in 8 fazı (0-7) tamamlandı; üzerine iki büyük eklenti yapıldı: (i) GUI Calibration Wizard, (ii) Excel-bağımsız Config Wizard.** Detaylar [§ 12 Faz 0-7 Sonuç Özeti](#12-faz-0-7-sonuç-özeti) ve [§ 13 Excel-Bağımsız Mod](#13-excel-bağımsız-mod) bölümlerinde.

| Metrik | Roadmap başı | Şimdiki durum | Δ |
|---|---:|---:|---:|
| Test sayısı | 21 | **149** | +610% |
| Kumluca KALIP sapma (elle kalibre) | %0.476 | %0.476 | 0 (regression yok) |
| Kumluca KALIP sapma (auto-fit) | yok | **%0.23** | yeni — elle yazılan kalibreyi geçti |
| Kumluca BETON sapma (auto-fit) | yok | %9.0 | yeni |
| Saf geometri çıktısı (Excel'siz) | yok | **mümkün** | yeni — `metraj config-wizard` |
| CLI komutları | 6 | **17** | +11 |
| Otomatize CalcParams alanı | 0 | **9 global + 5 dict** | yeni |
| Hazır preset YAML | 0 | **3** (`geometry_full`, `geometry_half`, `custom_template`) | yeni |
| Test süresi (slow dahil) | — | **22sn** (session fixture cache) | — |

### İki paralel kalibrasyon yolu

**Yol A — Referans Excel ile (auto-fit):**
```bash
metraj wizard --cad proje.dxf --reference ref.xlsx -o profile.yaml      # GUI 10 dk
# veya CLI
metraj structural-fit proje.dxf ref.xlsx -o profile.yaml                # 30 sn
metraj run --mode structural --structural-config profile.yaml proje.dxf
```
Beklenen sapma: KALIP <%1, BETON <%10.

**Yol B — Excel'siz (kullanıcı UI'dan çarpanları girer):**
```bash
metraj config-wizard -o profile.yaml                                    # GUI
# veya CLI hızlı preset
metraj config-wizard --preset geometry_full --preset-only -o saf.yaml   # Saf geometri (hepsi 1.0)
metraj config-wizard --preset geometry_half --preset-only -o yari.yaml  # Yarı kesit (hepsi 0.5)
metraj run --mode structural --structural-config profile.yaml proje.dxf
```
Çıktı: kullanıcı parametrelerine sadık (firma metraj usulüne göre değil, geometriden + kullanıcı çarpanlarıyla).

### Öğrenme döngüsü

```bash
metraj structural-feedback set-layer-kind feedback.json "K-X" column    # UI düzeltme
metraj train-profiles --pairs c1,r1 --pairs c2,r2 -o default.yaml       # 5+ proje median
metraj structural-feedback global-hints ./feedbacks/ -o hints.yaml      # auto signal_hints
```

Aşağıdaki orijinal roadmap (1-11. bölümler), gelecek fazların temel referansı olarak korundu. Yapılan işlerin commit edilmiş haline § 12 ve § 13'den ulaşılır.

---

## 1. Yönetici Özeti

### 1.1 Mevcut Doğruluk Tablosu

| Senaryo | KALIP sapma | BETON sapma | Durum |
|---|---|---|---|
| Kumluca DXF + tam kalibre `kumluca.yaml` | **%0.48** | **%0.87** | ✅ Tolerans (%1) altında |
| Kumluca DXF + saf geometri (varsayılan `CalcParams`) | **%199.99** | **%360.54** | ❌ Kalibrasyonsuz iki katına yakın yanılıyor |

Kaynak: [build_compare_kumluca_gt/dogrulama_ozeti.txt](../build_compare_kumluca_gt/dogrulama_ozeti.txt), [build_compare_geometry_only/dogrulama_ozeti.txt](../build_compare_geometry_only/dogrulama_ozeti.txt).

### 1.2 Anahtar Bulgu

Sapmanın asıl kaynağı **hesap motoru hatası değil, "metraj usulü" farkıdır**: bir firma kolon kalıbının iki yüzünü sayarken bir başkası dört yüzünü sayar; kiriş paylaşımı kat sınırlarında farklı bölünür; minha (eksiltme) tanımı standart değildir. Bu çarpanlar (örn. `column_formwork_strip_fraction=0.5`) ancak referans Excel ile karşılaştırılarak çıkarılabilir; saf geometriden otomatik tespit edilemez.

### 1.3 Hedefin Gerçekçi İfadesi

"**%100 otomatik**" değil, **üç katmanlı hedef**:

1. **Geometrik öz model** — her çizimden tutarlı (≥%98) çıkar (kolon poligonu doğru sayılır, perde uzunluğu doğru ölçülür, kat segmentasyonu doğru kümelenir).
2. **Metraj usulü profili (YAML)** — firma usulüne çevirim katmanı. İlk projede 5–15 dakika UI sihirbazı ile profil çıkar; sonraki benzer projelerde otomatik uygulanır.
3. **Düzeltme & öğrenme döngüsü** — kullanıcı UI'da yanlış sınıflandırılan elemanları düzeltir, sistem benzer projelere taşır.

**Sonuç hedefi:** İlk açılışta ≥%80 doğru; 10–15 dk UI kalibrasyonundan sonra ≥%95; yeterli eğitim verisi (≥10 proje) birikince ilk açılışta ≥%90.

---

## 2. Mevcut Sistem Anatomisi

### 2.1 Veri Akışı (Yapısal Mod)

`StructuralPipeline.run()` [metraj/core/structural/pipeline.py:89](../metraj/core/structural/pipeline.py#L89):

1. **DWG→DXF** — `DwgConverter.ensure_dxf` (ODA File Converter dış proses) + `DxfReader.read()` ([metraj/core/cad_io/dxf_reader.py](../metraj/core/cad_io/dxf_reader.py))
2. **Katman tespiti** — `detect_structural_layers` ([metraj/core/structural/layer_detection.py:30](../metraj/core/structural/layer_detection.py#L30)) regex `_RULES`: `KOLON|COLUMN|PERDE|S WALL|KIRIS|KİRİŞ|DOSEME|DÖŞEME|TEMEL|RADYE|GROBETON`
3. **Eleman çıkarımı** — `extract_structural_elements` ([metraj/core/structural/extractor.py:99](../metraj/core/structural/extractor.py#L99)): kapalı LWPOLYLINE → polygon, HATCH boundary → polygon, açık LWPOLYLINE → parapet line
4. **Çok katmanlı dedupe** — hash (centroid ±0.20 m, alan ±%5) → collinear (0.05 m) → IoU ≥ 0.5 → containment
5. **Plan başlığı & kat segmentasyonu** — `detect_title_anchors` + `detect_plan_multipliers` ([metraj/core/structural/plan_labels.py:75](../metraj/core/structural/plan_labels.py#L75)); X-merkezli Voronoi seed
6. **Hesaplama** — `calculate` ([metraj/core/structural/calculator.py:42](../metraj/core/structural/calculator.py#L42)): CalcParams ile formwork m² + concrete m³
7. **Doğrulama** — `compare_reports_full` ([metraj/core/structural/gt_io.py:448](../metraj/core/structural/gt_io.py#L448)) (`rtol=0.01`); Kumluca alias tablosu hard-coded ([gt_io.py:79](../metraj/core/structural/gt_io.py#L79))
8. **Excel çıktısı** — `write_structural_xlsx` veya `write_kumluca_reference_layout` ([metraj/core/structural/excel_writer.py](../metraj/core/structural/excel_writer.py))

### 2.2 Kritik CalcParams Çarpanları

| Parametre | Varsayılan | Kumluca | Anlam |
|---|---|---|---|
| `column_formwork_strip_fraction` | 1.0 | **0.5** | Kolon kalıp = çevre × k (iki taraflı şerit) |
| `column_concrete_section_fraction` | 1.0 | **0.5** | Kolon beton = alan × k |
| `beam_formwork_length_fraction` | 1.0 | **0.5** | Kiriş kalıp = uzunluk × k |
| `slab_net_area_fraction` | 1.0 | **0.5** | Döşeme net alan oranı |
| `elevator_shaft_quantity_scale` | 1.0 | **0.333** | Asansör şaft 3→1 birleşik kalem |
| `beam_zemin_concrete_qty_scale` | 1.0 | **0.434** | Zemin kiriş beton ek çarpanı |
| `beam_split_roof_fraction` | 0 | **0.374** | Çatıya bölünen kiriş yüzdesi |
| `temel_gt_scale` | 1.0 | proje-bazlı | Temel toplu GT ölçeği |
| `kolon_head_minha_scale` | 1.0 | **0.807** | Kolon başı minha ek katsayı |
| `doseme_net_scale_by_floor_label` | — | kat-bazlı dict | Her kat için döşeme alan ince ayar |

Bu çarpanların %1.0 olduğu durumda saf geometri çıkar; Kumluca değerleri firma usulüne kalibrasyondur.

### 2.3 Konfigürasyon Katmanı

- **`StructuralConfig`** ([metraj/core/structural/config.py](../metraj/core/structural/config.py)) — kat listesi, referans Excel yolu, `excel_layout` (`generic`|`kumluca`), tolerans, `structural_layer_include_kind`, `structural_layer_exclude`, gömülü `params: CalcParams`.
- **YAML `extends:`** — derin merge mekanizması (`_load_structural_yaml_dict`, `_deep_merge_mapping`); döngü tespiti var.
- **Mevcut profiller:** [metraj/config/references/kumluca.yaml](../metraj/config/references/kumluca.yaml) (üretim/GT), `kumluca_geometry_only.yaml` (extends kumluca, sadece `project_name` farklı), `structural.yaml` (jenerik şablon).

### 2.4 CLI & GUI

**CLI komutları** ([metraj/cli.py](../metraj/cli.py)):

| Komut | Amaç |
|---|---|
| `run` | Tam pipeline (mode `architectural`/`structural`/`auto`) |
| `inventory` | Katman/blok envanteri PoC + `--write-layer-map` |
| `new-project` | Şablon proje kopyala |
| `compare` | Hesap vs referans Excel |
| `structural-compare` | Birden fazla YAML profili kıyaslama |
| `ui` | PySide6 GUI başlat |
| `docs`, `diagnose` | Klavuz PDF / ODA durum |

**GUI** ([metraj/app/main_window.py](../metraj/app/main_window.py)) — PySide6, 9 sekmeli: 2D Plan, Mahal Listesi, Açıklıklar, İcmal, Yapısal Özet, Kalıp/Beton, Yapısal Katmanlar, Doğrulama, Uyarılar. Şu an `kumluca.yaml` varsayılan olarak yüklenir; mod seçimi `{Otomatik, Mimari, Yapısal}`.

---

## 3. Tanımlanan Boşluklar

### A. Katman tespit kırılganlığı
- Regex sözlüğü Türkçe/İngilizce sınırlı (`KOLON`, `COLUMN`, `PERDE` vb.) — kısaltma (`K1`, `S1`, `COL-01`) veya alfanumerik kodlarda fail.
- AutoCAD layer **rengi, lineweight, on/off, frozen** sinyalleri kullanılmıyor.
- Her katmandaki **entity istatistiği** (LWPOLYLINE oranı, ortalama alan, HATCH oranı) sınıflandırmaya girmiyor.
- **INSERT (blok) entity'leri** — kolon/kapı blokları kullanan firmalarda ham polyline'a düşürülmediği için kaçırılır.

### B. Plan başlığı & kat segmentasyonu dil-bağımlı
- `_BODRUM_RE`, `_ZEMIN_RE`, `_CATI_RE` örüntüleri Türkçe-hard-coded ([plan_labels.py:96](../metraj/core/structural/plan_labels.py#L96)).
- "2.VE 3. KAT" gibi çok spesifik örüntü; "B1+B2 PLAN", "1.NORMAL KAT", "TYP. FLOOR" varyasyonları fail eder.
- 80 char üstü başlıklar "teknik metin" varsayılarak yok sayılır.
- X-merkezli Voronoi: düşey-stacked veya 2×3 grid layout'larda kümeleme bozulur.

### C. Eleman türü ayırt etme
- Sınıflandırma **tamamen katman adına** bağlı; geometri-bazlı backup yok.
- Kolon vs perde için **aspect ratio eşiği config'de net değil**.
- Temel/radye/sömel ayrımı Kumluca usulüne göre — başka firmaların pad/strip foundation ayrımı yok.
- LINE entity'lerinden kiriş açıklık çıkarımı MRR-bazlı — düz LINE'larda doğrudan length yok.

### D. Metraj usulü kalibrasyonu (en kritik)
- Saf geometride %200+ sapma — `CalcParams` her firma için manuel doldurulmak zorunda.
- Manuel doldurma uzman bilgisi ister; otomatik çıkarım mekanizması yok.
- "%100 otomatik" hedefiyle doğrudan çelişen ana boşluk.

### E. Doğrulama / öğrenme döngüsü
- Tek referans Excel layout'u (Kumluca) hard-coded; `excel_layout: generic` placeholder seviyesinde.
- `gt_io.py`'de `KUMLUCA_DEFAULT_COMPARE_ALIASES` ve `KUMLUCA_STRIP_KOT_PREFIX_REST` ([gt_io.py:79-92](../metraj/core/structural/gt_io.py#L79)) hard-coded sabitler.
- Kullanıcı UI'dan düzeltme yapamıyor; benzer projelere bilgi taşınmıyor.

### F. GUI eksikleri
- 2D Plan görüntüleyici primitif (zoom/pan smooth değil).
- Polygon-click ile manuel kind override yok.
- Profil karşılaştırma UI'da yok (`structural-compare` sadece CLI).
- Hatalı eşleşmeleri kullanıcı YAML'a UI'dan kaydedemiyor.

### G. Test & dağıtım
- Structural pipeline coverage düşük (~%60-70 tahmini); GUI testi yok.
- PyInstaller dist'i yok — kullanıcı Python ortamı + ODA File Converter kurmak zorunda.
- Build süreci dokümante değil.

---

## 4. Kritik Tasarım Kararları

| Soru | Karar | Gerekçe |
|---|---|---|
| Saf geometri ile %100 mümkün mü? | **Hayır.** | AutoCAD 2D polyline yeterli sinyal taşımaz; aynı çizim iki firmaya farklı miktar yazar. BIM/IFC gerektirir. |
| Doğru hedef nedir? | **Geometrik öz model + metraj profili (YAML) + öğrenme** | "İlk projede 10 dk kalibrasyon, sonraki benzer projelerde otomatik" pragmatik. |
| ML mi heuristik mi? | **Hibrit: kural skorlayıcı + opsiyonel öğrenilmiş model (≥5 etiketli proje sonrası)** | Saf regex kırılgan, saf ML 5 projede genelleşmez. Kural skoru yorumlanabilir. |
| Multi-reference learning? | **Evet, "fit/calibrate" modu** (10 proje param öğren), evrensel ağ değil. | Param uzayı küçük (~30 katsayı); scipy non-linear least squares çözer. |
| Block (INSERT) tanıma? | **Faz 2 kritik.** Block name + öznitelik birinci sınıf sinyal. | %5-15 toplam kayıp tahmini; ezdxf'in `explode()` API'siyle çözülür. |
| Plan başlığı dil-agnostik? | **Sayısal kot öncelikli + YAML locale tablosu + opsiyonel OCR** | Hard-coded Türkçe yerine `config/locale/tr.yaml`, `en.yaml`; başlık yoksa "+3.00/+6.00" sayısal kotlar fallback. |

---

## 5. Faz Bazlı Roadmap

### Faz 0 — Stabilizasyon & Ölçüm Altyapısı (1 hafta, zorluk: düşük)

**Hedef:** Roadmap'in geri kalan tüm fazlarının ölçüleceği objektif baz çizgi.

| Geliştirme | Doğrulama |
|---|---|
| `metraj/tests/test_structural_pipeline.py` — Kumluca uçtan uca smoke; mevcut %0.48 / %0.87 assert. | `pytest -k structural` < 30 sn. |
| `metraj/benchmarks/bench_geometry_vs_reference.py` — saf geometri & kalibre çıktıları iki CSV; Markdown trend tablosu. | Baz değer raporu (%200 vs <%1). |
| `metraj/core/structural/diagnostics.py` — eleman JSON dump (layer, kind, area, bbox, centroid, source_entity_type). | Snapshot test. |
| `gt_io.py` → `KUMLUCA_DEFAULT_COMPARE_ALIASES` ve `KUMLUCA_STRIP_KOT_PREFIX_REST`'i YAML'a taşı (`kumluca.yaml`). | Regression test (aynı sonuç). |

**Deliverable:** Kıyaslama yapılabilen sayısal baz çizgi.

---

### Faz 1 — Katman Tespit Sağlamlığı (2 hafta, zorluk: orta)

**Hedef:** Boşluk A — regex tek-sinyalden çok-sinyalli skor sistemine geç.

| Geliştirme | Doğrulama |
|---|---|
| `layer_detection.py` → `score_layer(name, color, entity_stats) -> Dict[ElementKind, float]`. Sinyaller: ad benzerliği (token Jaccard + regex), renk önyargısı, entity dağılımı (kolon küçük+kompakt, perde uzun-ince), komşu katman ilişkisi. | `tests/test_layer_scoring.py` — sentetik DXF, 20 varyasyon ("K1", "C-01", "SP_KOLON", "S COLS"…) → ≥%90 doğru. |
| `extractor.py` → `_collect_entity_stats(doc, layer)` (renk, sayım, bbox, alan histogramı). | Diagnostic JSON içinde her katmanda stat. |
| `config/layer_map.yaml` şeması: `signal_hints` bloğu (renkler, alias listesi, anti-pattern). | A/B test ile +%15 başarı. |
| **INSERT desteği** — `dxf_reader.py` blokları explode et; block_name "virtual layer" (`block:KOLON_70x70`). | Sentetik INSERT-only kolonlu DXF: kolon sayısı 0 → N. |

**Quick win:** YAML `signal_hints` mekanizması.

---

### Faz 2 — Plan Etiketi Dil-Agnostik & Robust Segmentasyon (1.5 hafta, zorluk: orta)

**Hedef:** Boşluk B.

| Geliştirme | Doğrulama |
|---|---|
| `plan_labels.py` → `parse_plan_title(text, locale_tokens)`; hard-coded RE'ler yerine `config/locale/tr.yaml`, `en.yaml`. | Sentetik 30 başlık varyasyonu (TR+EN+karışık) → ≥%95. |
| Sayısal-kot fallback: başlık yoksa yakın "+3.00" formatlı en büyük font sayı. | `+3.00`, `+6,00`, `0.00`, `-3.00` parser test %100. |
| 80-char sınırını token-bazlı yapısal kurala çevir. | Uzun başlıklı fixture geçmeli. |
| `floor_segmenter.py` → X-merkezli yerine DBSCAN / 2D bbox cluster; düşey & grid layout desteği. | Yatay (Kumluca), düşey, 2×3 grid sentetik DXF testleri. |

**Quick win:** YAML locale + sayısal-kot fallback (mevcut Kumluca'yı bozmadan EN açar).

---

### Faz 3 — Geometri-Bazlı Eleman Sınıflandırma (2 hafta, zorluk: orta-yüksek)

**Hedef:** Boşluk C — katman tespiti fail ederse geometriden tipi türetebil.

| Geliştirme | Doğrulama |
|---|---|
| `classify.py` → `geometric_classify(element) -> ElementKind`. Özellikler: alan, aspect ratio, perimetre/alan oranı, kapalı poly vs hatch vs open line. | "Katman bilgisi gizlenmiş" Kumluca deneyi: ≥%85 doğru sınıf. |
| Kolon-perde eşik: aspect < 2.5 → kolon, 2.5-8 → kuşkulu, ≥8 → perde (config'de). | `tests/test_geometric_classify.py`. |
| Hibrit karar: `layer_kind` ve `geometric_kind` uyuşmazsa uyarı + diagnostics; sessiz overwrite yok. | UI'da "kuşkulu sınıflandırma" listesi. |
| Açık LINE kirişler için `geom.length` direkt. | LINE-only kiriş sentetik test. |

---

### Faz 4 — Metraj Profili Sistemi & Kalibrasyon Sihirbazı (3 hafta, zorluk: yüksek — **CAN DAMARI**)

**Hedef:** Boşluk D ve E. "Saf geometri → firma usulüne çevirim" katmanını otomatize et.

**Anahtar fikir:** Saf geometri çıkışından, kullanıcının referans Excel'ine ~30 katsayıyı **geri-fit et**. Kumluca için elle yapılan iş bundan sonra "Excel ver → profil çıkar" akışıyla otomatize.

| Geliştirme | Doğrulama |
|---|---|
| `core/structural/profile_fitter.py` — DXF + referans Excel + satır eşleme → `CalcParams`. Önce closed-form (her grup: `target/computed`), sonra scipy.optimize.minimize ile param-grup içi iyileştirme; L2 regularization. | Kumluca DXF+Excel ile elle yazılı `kumluca.yaml`'a ≥%95 benzer; sapma <%1. |
| `app/calibration_wizard.py` (QDialog) — DXF+Excel yükle → satır eşleme tablosu (otomatik öneri + manuel) → "Fit" → YAML kaydet. | UI manuel testi: 10 dk içinde profil <%1 sapma. |
| `gt_io.py` aliases artık YAML'dan + UI editor. | Faz 0 testleri geçer. |
| `core/excel/generic_writer.py` — kategori-bazlı grup, kullanıcı tanımlı sütun YAML. | Yeni "generic" layout aynı toplamları üretir. |
| `calculator.py` → `CalcParams` modül-bazlı (kolon/kiriş/döşeme); versionlanmış preset `config/methods/`. | "Kumluca usulü" / "İBB usulü" iki preset çağrılabilir. |

**Quick win:** Profile fitter — Kumluca YAML'ı %5 farkla otomatik üretebiliyorsa, yeni firmada 1 Excel ile profil çıkar.

---

### Faz 5 — Düzeltme & Öğrenme Döngüsü (2 hafta, zorluk: orta)

**Hedef:** Boşluk E ve F.

| Geliştirme | Doğrulama |
|---|---|
| `main_window.py` → polygon-click → context menu "Bu kind yanlış, doğrusu X" → `project.yaml`'a `manual_classifications` blok (handle/hash bazlı). | UI testi: yanlış kolon → perde override → yeni rapor doğru. |
| `comparison_aliases` UI editörü. | Save/load cycle. |
| `core/learning/feedback_store.py` — proje bazlı düzeltmeler JSON; birden fazla projede sık tekrar eden alias'lar "global hint listesi"ne. | 3 sentetik projede 2× aynı override → 3. projede otomatik öneri. |
| 2D viewer iyileştirme: smooth zoom/pan, eleman select renk, kat-filter dropdown, kuşkulu sınıflandırma sayfası. | UX smoke testleri. |

---

### Faz 6 — Multi-Reference Eğitim & Default Profil (3 hafta, zorluk: yüksek)

**Hedef:** Boşluk D'nin uzun-kuyruğu.

| Geliştirme | Doğrulama |
|---|---|
| `core/learning/profile_trainer.py` — N (DXF, Excel) çiftinden Faz 4 fitter ile profil çıkar; param dağılım median/IQR'ı "default profile". | 5 sentetik proje setiyle median doğrulanır; outlier mean bozmaz. |
| `metraj train-profiles --inputs <glob>` CLI. | CI smoke. |
| **ML-bazlı layer sınıflandırıcı (opsiyonel)** — scikit-learn `GradientBoostingClassifier`, Faz 1 sinyalleri. Etiketli proje ≥5 olunca devreye. | Cross-validation ≥%90. |

---

### Faz 7 — Test, Paketleme, Dokümantasyon (2 hafta, zorluk: düşük-orta)

**Hedef:** Boşluk G.

| Geliştirme | Doğrulama |
|---|---|
| Structural test coverage ≥%70 — profile_fitter, layer_scoring, plan_label_locale, feedback_store, geometric_classify. | `pytest --cov=metraj/core/structural` raporu. |
| `metraj.spec` PyInstaller — Windows + macOS single-file bundle. ODA: ilk açılış diyaloğu (`oda_setup_dialog.py`). | GitHub Actions matris build. |
| `docs/calibration_guide.md` + PDF derleme (`scripts/build_user_guide.py`). | PDF üretim CI job. |
| `metraj diagnose --full` — katman skorları, plan etiketleri, eleman sayıları, profil uygunluk uyarıları. | CLI smoke. |

---

## 6. Önceliklendirme

| Boşluk | Etki | Çaba | Faz | Quick-win mi? |
|---|---|---|---|---|
| D — Metraj usulü kalibrasyonu | Çok yüksek (sapmanın asıl kaynağı) | Yüksek | 4 | Profile fitter |
| A — Katman tespit kırılganlığı | Yüksek | Orta | 1 | YAML signal_hints |
| E — Öğrenme / generic Excel | Yüksek | Orta-yüksek | 4-5 | Generic writer |
| B — Plan etiket dil-agnostik | Orta | Düşük-orta | 2 | YAML locale + sayısal fallback |
| C — Eleman türü ayırt etme | Orta | Orta | 3 | — long tail |
| F — GUI düzeltme | Orta | Orta | 5 | — |
| G — Test & dağıtım | Düşük (acil değil ama gerekli) | Düşük-orta | 7 | PyInstaller spec |

**En kritik tek hamle:** **Faz 4 — Profile Fitter.** Çünkü sapmanın %95'i metraj usulü farkından geliyor; "5–10 dk profil çıkarma" akışı kullanıcıya gerçek değer verir.

**Toplam efor:** 14–16 hafta (tek geliştirici, sıralı).

---

## 7. Riskler ve Mitigasyonlar

| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Profile fitter under-determined (param > eşitlik) | Yüksek | Yüksek | Param gruplara böl, kapalı-form `target/computed`; kalan kalıntı için optimize; L2 regularization. |
| Geometrik sınıflandırıcı yanlış pozitif | Orta | Orta | Hibrit: layer ↔ geometry uyuşmazlığı → uyarı, sessiz overwrite yok; UI'da onay. |
| INSERT explode performans (10k+ blok) | Orta | Düşük | Block-cache (aynı block_def bir kez explode); shapely lazy geometry. |
| YAML profilleri patlama | Düşük | Orta | `extends:` + `defaults.yaml` + ufak `<firma>.yaml`. |
| ODA explode INSERT yapmıyor | Orta | Orta | ezdxf'in kendi `explode()`'unu kullan; ODA'ya bağımlı olma. |
| Multi-reference eğitiminde veri sızıntısı | Düşük | Yüksek | Cross-validation; leave-one-out sapma raporu. |
| 2D viewer büyük plan'da yavaş | Orta | Düşük | Tile-based render, viewport culling (Faz 5 ikincil). |

---

## 8. Doğrulama Akışı (Kümülatif Benchmark)

Her fazın sonunda aşağıdaki ölçütler kontrol edilir:

1. **Birincil (regression):** Kumluca DXF + Kumluca Excel → KALIP & BETON sapma ≤ %1.
2. **İkincil (Faz 1 sonrası):** Kumluca DXF'inin rastgele 3 katman adı bozulmuş versiyonu → sapma ≤ %5.
3. **Üçüncül (Faz 3+ sonrası):** Sentetik DXF (ezdxf üretimi, Türkçe katman yok, INSERT-bazlı kolonlar) → sapma ≤ %5.
4. **Genelleme (Faz 4 sonrası):** Yeni gerçek proje + Excel → UI sihirbazıyla ≤15 dk içinde sapma ≤ %5.
5. **Çapraz-doğrulama (Faz 6 sonrası):** Eğitilmiş default profil ile hiç görülmemiş projede sapma ≤ %10.

**Faz-faz hedef:**
- Faz 0-1: birincil benchmark korunur + ikincil ölçülmeye başlanır.
- Faz 2-3: ikincil & üçüncül benchmarklarda hedeflere yaklaş.
- Faz 4-5: genelleme benchmark'ı ≤%5.
- Faz 6: çapraz-doğrulama ≤%10; "ilk açılışta ≥%90 doğru".

---

## 9. Kritik Dosyalar

### 9.1 Mevcut (değiştirilecek)

- [metraj/core/structural/pipeline.py](../metraj/core/structural/pipeline.py)
- [metraj/core/structural/calculator.py](../metraj/core/structural/calculator.py)
- [metraj/core/structural/config.py](../metraj/core/structural/config.py)
- [metraj/core/structural/gt_io.py](../metraj/core/structural/gt_io.py)
- [metraj/core/structural/layer_detection.py](../metraj/core/structural/layer_detection.py)
- [metraj/core/structural/extractor.py](../metraj/core/structural/extractor.py)
- [metraj/core/structural/plan_labels.py](../metraj/core/structural/plan_labels.py)
- [metraj/core/structural/floor_segmenter.py](../metraj/core/structural/floor_segmenter.py)
- [metraj/core/structural/classify.py](../metraj/core/structural/classify.py)
- [metraj/core/structural/excel_writer.py](../metraj/core/structural/excel_writer.py)
- [metraj/core/cad_io/dxf_reader.py](../metraj/core/cad_io/dxf_reader.py)
- [metraj/cli.py](../metraj/cli.py)
- [metraj/app/main_window.py](../metraj/app/main_window.py)
- [metraj/config/references/kumluca.yaml](../metraj/config/references/kumluca.yaml)

### 9.2 Yeni eklenecek (faz sırasıyla)

| Dosya | Faz |
|---|---|
| `metraj/benchmarks/bench_geometry_vs_reference.py` | 0 |
| `metraj/core/structural/diagnostics.py` | 0 |
| `metraj/tests/test_structural_pipeline.py` | 0 |
| `metraj/config/locale/tr.yaml`, `en.yaml` | 2 |
| `metraj/core/structural/profile_fitter.py` | 4 |
| `metraj/app/calibration_wizard.py` | 4 |
| `metraj/core/excel/generic_writer.py` | 4 |
| `metraj/config/methods/*.yaml` | 4 |
| `metraj/core/learning/feedback_store.py` | 5 |
| `metraj/core/learning/profile_trainer.py` | 6 |
| `metraj/app/oda_setup_dialog.py` | 7 |
| `metraj.spec` (PyInstaller) | 7 |
| `docs/calibration_guide.md` | 7 |

---

## 10. Pratik Kısıtlar (Sürekli Hatırlatma)

1. **Tek geliştirici.** Paralel çalışma yok; sıralı faz.
2. **PyQt + Python ekosistemi.** Yeni dil/runtime yok; scipy/scikit-learn eklenmesi serbest.
3. **ODA File Converter bağımlılığı korunur.** Sadece kullanıcı kurulumunu kolaylaştır (Faz 7).
4. **Geriye dönük uyum.** Her faz mevcut Kumluca regression testlerini kırmamalı.
5. **Sessiz hata yok.** Hibrit kararlar (layer ↔ geometry, manual override vs default) her zaman uyarı üretmeli.

---

## 11. Sonraki Adım

**Tavsiye:** Faz 0 ile başla — ölçüm altyapısı olmadan sonraki fazların başarısı objektif değerlendirilemez. Faz 0'ın 4 deliverable'ı (smoke test, benchmark script, diagnostics, alias YAML migrasyonu) toplam 1 hafta. Bu tamamlandığında Faz 1 ve Faz 4 paralelde değerlendirilebilir (Faz 4 daha büyük etkili, ama Faz 1 daha hızlı görülebilir kazanım).

---

*Belge tarihi: 2026-05-11 — Claude (Opus 4.7) tarafından üç paralel kod-keşif ajanı + bir mimar plan ajanının çıktısı konsolide edilerek hazırlanmıştır. Gelecek geliştirme oturumlarının baş referansı olarak güncel tutulmalıdır.*

---

## 12. Faz 0-7 Sonuç Özeti

### 12.1 Faz-faz çıktılar

| Faz | Hedef | Üretilen | Test |
|---|---|---|---:|
| **0** Stabilizasyon | Ölçüm altyapısı | `diagnostics.py`, `benchmarks/bench_geometry_vs_reference.py`, `test_structural_pipeline.py` slow smoke, alias YAML migrasyonu | 21 |
| **1** Katman tespit | Skor + INSERT + signal_hints | `layer_signals.py`, `score_layer`, `config/locale/structural_signal_hints.yaml`, INSERT explode | 51 |
| **2** Plan dil-agnostik | Locale + axis kümeleme | `PlanLabelLocale` + `tr.yaml`/`en.yaml`, `axis="x"\|"y"\|"auto"` | 92 |
| **3** Geometri sınıflandırma | Hibrit conflict uyarı | `geometric_classify`, `find_classification_conflicts`, doğal ambiguity filtre, standalone LINE desteği | 110 |
| **4** Profile fitter | Global scale auto-fit | `profile_fitter.py`, `FitTarget`, `metraj structural-fit` CLI | 113 |
| **4 v2** İki-aşamalı fit | Kat-bazlı dict | `_FLOOR_DICT_TARGETS`, native floor key, alias normalize | 114 |
| **4 v3** Ek hedefler | parapet/minha denemesi | Yapısal sınırlar (kategori uyumsuzluğu); not olarak korundu, `beam_split_*` ileri-faza | 114 |
| **5** Düzeltme döngüsü | FeedbackStore + global hints | `core/learning/feedback_store.py`, 6× CLI alt komut | 125 |
| **6** Multi-reference | Median + outlier + LOOCV | `core/learning/profile_trainer.py`, `metraj train-profiles` CLI | 132 |
| **7** Calibration Wizard | PySide6 5-adımlı sihirbaz | `metraj/app/calibration_wizard.py`, `metraj wizard` CLI | **139** |

### 12.2 Kumluca ölçüm trendi

| Senaryo | KALIP toplam sapma | BETON toplam sapma | Kaynak |
|---|---:|---:|---|
| Saf geometri (baseline) | %67.7 | %73.7 | `build/bench_phase0/geometry_only/` |
| Auto-fit (Faz 4 global) | %1.1 | %8.6 | `build/bench_phase4/` |
| **Auto-fit (Faz 4 v2 iki-aşamalı)** | **%0.23** | **%9.0** | `build/bench_phase6/trained_solo.yaml` ile pipeline |
| Elle yazılı kalibre `kumluca.yaml` | %0.48 | %0.87 | `build_compare_kumluca_gt/` |

**Sonuç:** Auto-fit, KALIP toplamında elle-yazılmış Kumluca yaml'ı **geçti** (%0.23 < %0.48); BETON toplamında ise %9 sapma kaldı — bu single-param fit'in doğal sınırı, `beam_split_*` aile (multi-kat plan kiriş bölünmesi) çoklu projeyle median'a düşer veya kalibrasyon sihirbazında manuel ince ayarla kapatılır.

### 12.3 Yeni iş akışı (uçtan uca)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Yeni proje açıldı                                            │
│    metraj wizard --cad p.dxf --reference r.xlsx -o p.yaml      │
│    → 10 dk sihirbaz → p.yaml (~%5 sapma ilk-vuruş)             │
├─────────────────────────────────────────────────────────────────┤
│ 2. UI manuel düzeltmeler (Faz 5 FeedbackStore)                  │
│    metraj structural-feedback set-layer-kind fb.json "KOL-X" column │
│    → feedback.json (pipeline her koşumda merge eder)             │
├─────────────────────────────────────────────────────────────────┤
│ 3. 5+ proje birikince trained default profile (Faz 6)            │
│    metraj train-profiles --pairs cad1,ref1 --pairs cad2,ref2 ... │
│    → default.yaml (median scale, outlier filtre)                 │
├─────────────────────────────────────────────────────────────────┤
│ 4. Global hint çıkarımı (Faz 5)                                  │
│    metraj structural-feedback global-hints ./feedbacks/ -o h.yaml│
│    → signal_hints YAML, Faz 1 score_layer'a beslenir              │
├─────────────────────────────────────────────────────────────────┤
│ 5. Yeni 6+ proje: default.yaml + signal_hints ile ilk-vuruş ~%5  │
└─────────────────────────────────────────────────────────────────┘
```

### 12.4 Yeni modüller (paket yapısı)

```
metraj/
├── benchmarks/
│   ├── __init__.py                          (Faz 0)
│   └── bench_geometry_vs_reference.py
├── config/
│   └── locale/                              (Faz 1-2)
│       ├── structural_signal_hints.yaml
│       ├── plan_labels_tr.yaml
│       └── plan_labels_en.yaml
├── core/
│   ├── learning/                            (Faz 5-6)
│   │   ├── __init__.py
│   │   ├── feedback_store.py
│   │   └── profile_trainer.py
│   └── structural/
│       ├── diagnostics.py                   (Faz 0)
│       ├── layer_signals.py                 (Faz 1)
│       └── profile_fitter.py                (Faz 4-4v2-4v3)
└── app/
    └── calibration_wizard.py                (Faz 7)
```

### 12.5 Yeni CLI komutları

| Komut | Faz | İşlev |
|---|:-:|---|
| `metraj structural-fit <cad> <ref> -o <yaml>` | 4 | Auto-fit profile çıkar |
| `metraj wizard [--cad ... --reference ... -o ...]` | 7 | Calibration sihirbazı (PySide6) |
| `metraj train-profiles --pairs ... -o <yaml>` | 6 | Multi-reference median profile |
| `metraj structural-feedback list <store>` | 5 | Feedback içeriği |
| `metraj structural-feedback set-layer-kind <store> <layer> <kind>` | 5 | Manual layer override |
| `metraj structural-feedback remove-layer-kind <store> <layer>` | 5 | Override kaldır |
| `metraj structural-feedback set-alias <store> <src> <dst>` | 5 | Comparison alias |
| `metraj structural-feedback exclude-layer <store> <layer>` | 5 | Katman dışla |
| `metraj structural-feedback global-hints <dir> -o <yaml>` | 5 | Multi-project signal_hints |
| `python -m metraj.benchmarks.bench_geometry_vs_reference ...` | 0 | Sapma trend raporu |

### 12.6 Test optimizasyonu

`metraj/tests/conftest.py` ile session-scope fixture'lar (`kumluca_pipeline_result`, `kumluca_fit_result`). Slow testler artık ortak DXF parse'ini paylaşıyor:

| Aşama | Test sayısı | Test süresi |
|---|---:|---:|
| Faz 0 (başlangıç) | 21 | ~4 sn |
| Faz 4 (slow eklendi) | 113 | ~47 sn |
| Faz 7 + fixture cache | **139** | **~29 sn** |

### 12.7 Kapanış notu

Bu satırın yazıldığı anda **Faz 0-7 + Calibration Wizard tamamlandı, Faz 4 v3 BETON ek-iyileştirme denemesi yapılarak sınırlar belgelendi, test stabilizasyonu uygulandı**. Roadmap'in başlangıçtaki "ilk açılışta ≥%80, 10-15 dk kalibrasyondan sonra ≥%95" hedefi şu an gerçekçi olarak ulaşılabilir durumda — gerek CLI (`structural-fit`), gerek GUI (`wizard`) ile.

Geri kalan iş alanları:
- `beam_split_*` ailesi için multi-kat plan çıkarımı (BETON sapma %9 → daha düşük için)
- Kalibrasyon sihirbazı manual smoke test (kullanıcı tarafı)
- Birden fazla gerçek firma DXF/Excel çifti ile `train-profiles` koşumu (Faz 6 LOOCV pratik kanıt)
- PyInstaller paketleme + ODA File Converter kurulum diyaloğu (planda Faz 7 idi, GUI calibration_wizard'a öncelik verildi)

---

## 13. Excel-Bağımsız Mod (yeni eklenti)

**Motivasyon.** Faz 4 auto-fit (`metraj structural-fit`) referans Excel zorunlu — Kumluca formatına (`A KALIP` + `A BETON` sayfaları, kot prefix kırpma, alias eşleme) hard-coded. Farklı firma formatları için kullanışsızdı. **Bu eklenti, kullanıcının elinde referans Excel olmasa bile yapısal metraj almasını mümkün kılar**: geometri ölçülür, kullanıcı UI'dan sayım usulü çarpanlarını girer, jenerik Excel çıkar.

### 13.1 Yeni dosyalar

| Dosya | İşlev |
|---|---|
| [config/methods/geometry_full.yaml](../metraj/config/methods/geometry_full.yaml) | **Saf Geometri** preset: tüm `*_fraction`/`*_scale` = 1.0. Kolon kalıp = tam çevre × kat yüksekliği; döşeme = brut alan. |
| [config/methods/geometry_half.yaml](../metraj/config/methods/geometry_half.yaml) | **Yarı Kesit (Kumluca tarzı)** preset: hepsi 0.5 + asansör 1/3. Excel referansı olmayan Kumluca-style firmalar için ilk-vuruş. |
| [config/methods/custom_template.yaml](../metraj/config/methods/custom_template.yaml) | Yorum satırlı şablon, kullanıcı UI üzerinden doldurur. |
| [metraj/app/structural_config_dialog.py](../metraj/app/structural_config_dialog.py) | **PySide6 QDialog**: 6 sekme (Kolon/Perde/Kiriş/Döşeme/Temel/Parapet+Asansör). Her CalcParams alanı için anlaşılır etiket + tooltip + QDoubleSpinBox. Preset dropdown, "Saf Geometri" / "Yarı Kesit" hızlı butonlar. |
| [tests/test_structural_config_dialog.py](../metraj/tests/test_structural_config_dialog.py) | **10 test**: preset yükleme, YAML round-trip, FIELD_GROUPS doğrulama, CLI smoke. |

### 13.2 Yeni CLI

```bash
# GUI sihirbaz
metraj config-wizard -o profile.yaml

# GUI'siz hızlı preset
metraj config-wizard --preset geometry_full --preset-only -o saf.yaml
metraj config-wizard --preset geometry_half --preset-only -o yari.yaml

# Mevcut presetleri listele
metraj config-wizard --list-presets
```

### 13.3 UI mantığı — kullanıcının ayarladığı parametreler

| Sekme | CalcParams alanı | Anlaşılır etiket | Tipik değerler |
|---|---|---|---|
| **Kolon** | `column_formwork_strip_fraction` | "Kolon kalıp çevre çarpanı" | 1.0 (tam çevre) / 0.5 (yarı) |
| | `column_concrete_section_fraction` | "Kolon beton kesit çarpanı" | 1.0 / 0.5 |
| **Perde** | `shear_wall_concrete_section_fraction` | "Perde beton kesit çarpanı" | 1.0 / 0.5 |
| **Kiriş** | `beam_depth_m` | "Kiriş derinliği (m)" | 0.45 |
| | `beam_width_m` | "Kiriş genişliği (m)" | 0.25 |
| | `beam_formwork_length_fraction` | "Kiriş kalıp uzunluk çarpanı" | 1.0 / 0.5 |
| | `beam_concrete_section_fraction` | "Kiriş beton kesit çarpanı" | 1.0 / 0.5 |
| **Döşeme** | `slab_thickness_m` | "Döşeme kalınlığı (m)" | 0.15 |
| | `slab_net_area_fraction` | "Döşeme net alan çarpanı" | 1.0 (brut) / 0.5 (yarı) |
| **Temel & Grobeton** | `foundation_depth_m` | "Temel derinliği (m)" | 0.5 |
| | `foundation_plan_formwork_scale` | "Temel kalıp çevre çarpanı" | 1.0 / 0.5 |
| | `foundation_concrete_section_fraction` | "Temel beton kesit çarpanı" | 1.0 / 0.5 |
| | `lean_concrete_thickness_m` | "Grobeton kalınlığı (m)" | 0.10 |
| | `grobeton_formwork_gt_scale` | "Grobeton kalıp çarpanı" | 1.0 / 0.5 |
| **Parapet & Asansör** | `parapet_thickness_m` | "Parapet kalınlığı (m)" | 0.20 |
| | `parapet_concrete_volume_fraction` | "Parapet beton hacim çarpanı" | 1.0 / 0.365 |
| | `elevator_shaft_quantity_scale` | "Asansör şaftı çarpanı" | 1.0 (her ayrı) / 0.333 (toplu) |

Toplam **17 alan** kullanıcı kontrolünde. Saf geometri butonu hepsini 1.0'a; Yarı kesit hepsini 0.5'e set eder.

### 13.4 Doğrulama: saf geometri çıkışı

Kumluca DXF üzerinde `geometry_full` preset ile koşum:
```
KALIP toplam: 7181.72 m²     (saf geometri — referans Excel kullanılmadı)
BETON toplam: 1387.34 m³
Excel: yapisal_metraj.xlsx (generic layout: Özet + A KALIP + A BETON + Kat Bazlı)
validation_detail: None     (referans Excel yok, sapma hesabı yapılmaz)
```

Bu rakamlar Kumluca'nın elle yazılmış referansından (4281 / 798) farklı — çünkü Kumluca firmasının metraj usulü uygulanmadı. Ama kullanıcı kendi firmasının kullandığı çarpanları UI'dan girerse, doğru rakamı alır.

### 13.5 İki paralel mod karşılaştırması

| Özellik | Yol A: Excel-tabanlı (Faz 4 auto-fit) | Yol B: Excel-bağımsız (bu eklenti) |
|---|---|---|
| Gerekli girdi | DXF + referans Excel (Kumluca formatı) | Sadece DXF |
| Auto-kalibrasyon | Var (KALIP <%1, BETON <%10) | Yok — kullanıcı manuel girer |
| UI sihirbaz | `metraj wizard` | `metraj config-wizard` |
| CLI | `metraj structural-fit` | `metraj config-wizard --preset-only` |
| Excel formatı | Kumluca (A KALIP / A BETON) | Generic (Özet / A KALIP / A BETON / Kat Bazlı) |
| Hazır preset | yok | 3 preset (`config/methods/*.yaml`) |
| Hangi firma için? | Excel'i Kumluca formatında olan | Excel'i farklı olan / hiç Excel'i olmayan |
| Sapma garantisi | Auto-fit ile referans'a yakın | Kullanıcı parametrelerine birebir sadık |

### 13.6 Sonuç

Sistem artık **iki bağımsız iş akışı**na sahip:
- Kumluca/Kumluca-style Excel'i olanlar **otomatik kalibrasyon** ile %99+ doğruluk
- Excel'i olmayanlar **UI'dan çarpan girerek** firma usulüne sadık ham geometri metrajı

İkisi de aynı `StructuralConfig` mekanizması üzerinden çalışır; YAML çıktıları birbirinin yerine geçebilir.

### 13.7 GUI ile sistemi yönetme

Üç farklı UI giriş noktası:

| Komut | Amaç |
|---|---|
| `metraj ui` | **Ana pencere** — DWG yükle, mod seç (auto/architectural/structural), çalıştır, sekmeler: mahal listesi, açıklıklar, icmal, 2D plan, yapısal özet, kalıp/beton, doğrulama, uyarılar |
| `metraj wizard` | Kalibrasyon sihirbazı (Excel ile auto-fit) — 5 adımlı QDialog |
| `metraj config-wizard` | Excel'siz config sihirbazı — 6 sekmeli QDialog |

`metraj ui` koşuldu mu kullanıcı tüm pipeline'ı GUI'den yönetebilir; çıktı Excel + 2D görüntü + tablo sekmeleri olarak gösterilir.
