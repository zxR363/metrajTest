# Metraj — geliştirme özeti ve mevcut durum (LLM devretme)

Bu belge, projede yapılan işlemleri ve teknik gerçekleri özetler; başka bir dil modeli veya geliştirici repo’yu hızlı anlasın diye yazıldı.

---

## 1. Ürünün amacı

**Metraj**, DWG/DXF çizimlerinden yapısal (kaba inşaat) **kalıp (m²)** ve **beton (m³)** metrajı üretir. Mimari mahal metrajı (`Pipeline`, mimari mod) ile yapısal mod (`StructuralPipeline`) ayrıdır.

Bu dokümanda odak: **yapısal metraj** ve **Kumluca** referans projesi.

---

## 2. Veri akışı (yapısal)

1. **CAD → ham model**: `DwgConverter.ensure_dxf`, `DxfReader` (`metraj/core/cad_io/`).
2. **Katman / eleman**: `detect_structural_layers`, `extract_structural_elements`, planlara atama (`floor_segmenter`, `plan_labels` — plan başlığından kot ve `multiplier`).
3. **Hesap**: `calculate(smodel, CalcParams)` (`metraj/core/structural/calculator.py`).
4. **Çıktı**: Excel (`excel_writer`), isteğe bağlı **referans Excel ile doğrulama** (`gt_io.compare_reports_full`) → `dogrulama_ozeti.txt`.

**Önemli:** Çıktı rakamları DWG geometrisinden hesaplanır. Referans Excel **varsayılan olarak rapora kopyalanmaz**; `snap_rows_to_reference: true` olursa eşleşen satırlar referansa yapıştırılır (sapmayı gizleyebilir — geliştirme için).

---

## 3. Konfigürasyon katmanları

### 3.1 `StructuralConfig` (`metraj/core/structural/config.py`)

- Kat listesi, `reference_excel_path`, `excel_layout` (`generic` | `kumluca`).
- `compare_to_reference`, `validation_tolerance`, `comparison_label_aliases`.
- `snap_rows_to_reference`.
- `structural_layer_include_kind` / `structural_layer_exclude`.
- **`params`**: `CalcParams` örneği.

### 3.2 `CalcParams` (`calculator.py`)

Formül sabitleri ve **çarpanlar**: kolon şerit kesiri, döşeme net kesiri, kiriş bölme, kat bazlı ölçekler, `temel_gt_scale`, asansör çarpanı vb. Varsayılanlar çoğu yerde **1.0** (tam geometrik yorum).

### 3.3 YAML yükleme ve `extends`

`StructuralConfig.from_file` artık düz `yaml.safe_load` kullanmıyor; **`extends: taban.yaml`** ile derin birleştirme yapıyor (`_load_structural_yaml_dict`, `_deep_merge_mapping`). İç içe `params` sözlükleri birleştirilir; döngü tespiti var.

### 3.4 Kumluca referans dosyaları

| Dosya | Rol |
|--------|-----|
| `metraj/config/references/kumluca.yaml` | Üretim/GT doğrulama profili: dolu `params`, `compare_to_reference: true`, `snap_rows_to_reference: false`. |
| `metraj/config/references/kumluca_geometry_only.yaml` | **`extends: kumluca.yaml`** — tabanla **aynı ölçek/katsayı**; sadece `project_name` farklı. Eski anlamdaki “params yok saf geometri” profili **artık kullanılmıyor** (yanlış GT karşılaştırması üretiyordu). |

---

## 4. “Saf geometri” vs “Kumluca ölçeği” (kritik ayrım)

- **Kumluca `params`:** Firma Excel / GT ile uyum için birçok kesir ve ölçek (ör. kolon kalıp `column_formwork_strip_fraction: 0.5`, `slab_net_area_fraction: 0.5`, `elevator_shaft_quantity_scale: 1/3`, `beam_split_*`, kat bazlı `doseme_net_scale_*`, `temel_gt_scale`, …). Bunlar **referans tablodaki ölçüm diline** hizalanmış katsayılar; ham poligon “literal” toplamı değil.

- **Params’sız / varsayılan `CalcParams`:** Çoğu çarpan **1.0** → geometrik formülün “dolu kesir” olmadan” yorumu. Bu çıktıyı **aynı GT Excel ile** karşılaştırmak **adil değil** (~2× sapma gibi görünür); sorun çoğunlukla ölçüm tanımı farkı.

- **Aynı ölçekte GT sapması:** `kumluca.yaml` (veya onu extend eden profil) ile koşulan doğrulama, “çizim + sınıflandırma + **firma ölçüm tanımı**” altında kalan sapmadır. Örnek ölçü (Kumluca DXF + `kumluca kaba.xlsx`): KALIP max rel ~**0.48%**, BETON max rel ~**0.87%**, uyarı satırı sayısı ~**27** (eşik %1).

---

## 5. CLI ekleri

- **`python -m metraj.cli run --mode structural --structural-config <yaml> -o <dir> <cad>`** — tek yapısal koşu.
- **`python -m metraj.cli structural-compare <cad> --config A.yaml --config B.yaml -o <base>`** — aynı çizimi birden fazla YAML ile çalıştırır; toplamlar ve `dogrulama_ozeti` yollarını tabloda özetler (`metraj/cli.py` içinde `_cmd_structural_compare`).

---

## 6. Git / GitHub (yapılan operasyonel iş)

Büyük DXF/DWG dosyaları geçmişte commit’lere girdiği için push **GH001** ile reddediliyordu. Çözüm: geçmişten büyük blob’ları temizlemek (`git filter-repo --strip-blobs-bigger-than 50M` vb.), `origin` yeniden eklemek, **`git push --force`** (geçmiş yeniden yazılır — ekip uyarısı gerekir).

`.gitignore` ve `git rm --cached` tek başına yeterli değildir; sorun **tarihçedeki blob’lar**dır.

---

## 7. Firma bazlı kullanım (olası model)

Her firma için ayrı YAML (veya `extends` ile ortak taban + firma `params`) mümkün; referans Excel **zorunlu değil**. GT ile doğrulama istenirse `reference_excel_path` ve `compare_to_reference` açılır.

GUI (`main_window.py`) şu an paket içi **`kumluca.yaml`** yükleme eğiliminde; çok firma için **yapısal YAML dosyası seçimi** UI’da genişletilebilir (henüz talep üzerine yapılmadıysa dokümante et).

---

## 8. Testler (referans)

`metraj/tests/test_gt_reference.py`:

- `test_kumluca_yaml_validation_gate_one_percent` — Kumluca YAML parametre beklentileri.
- `test_extends_inherits_kumluca_params` — `kumluca_geometry_only.yaml`’ın tabanla aynı kritik `CalcParams` alanlarını taşıması.

---

## 9. Önemli dosya yolları (kısa indeks)

| Yol | İçerik |
|-----|--------|
| `metraj/core/structural/pipeline.py` | Orkestrasyon, doğrulama, Excel yazımı |
| `metraj/core/structural/calculator.py` | Formüller, `CalcParams` |
| `metraj/core/structural/config.py` | `StructuralConfig`, `extends` birleştirme |
| `metraj/core/structural/gt_io.py` | Referans parse, karşılaştırma, snap |
| `metraj/config/references/kumluca.yaml` | Kumluca üretim/doğrulama |
| `metraj/cli.py` | `run`, `structural-compare`, … |

---

## 10. Ürün iddiası nasıl ifade edilmeli?

- **Kumluca benzeri çizim + doğru yapılandırma** ile GT seviyesinde doğrulama **hedeflenmiş ve ölçülmüştür**.
- **Rastgele her DWG** için “otomatik doğru” **garanti edilemez** (katman adları, çizim disiplini, metraj usulü değişir).
- **Firma katsayıları** = firma YAML’ı; bu **Kumluca GT kalibrasyonundan bağımsız** bir kullanım modeli olarak düşünülebilir.

---

*Belge tarihi: geliştirme oturumu sonrası konsolidasyon. Kod değişiklikleri için repo geçmişine ve ilgili dosyalara bakın.*
