# Kalibrasyon Sihirbazı — Kullanım Kılavuzu

> **Amaç.** Yeni bir firma çiziminden ~10 dakika içinde özelleştirilmiş bir
> metraj profili (`*.yaml`) üretmek. Sihirbaz, [Faz 4 profile_fitter](../metraj/core/structural/profile_fitter.py)
> ve [Faz 4 v2 kat-bazlı ince ayar](#) algoritmalarını PySide6 GUI ile sarmalar.

---

## Hızlı başlangıç (60 saniye)

```bash
# Bağımlılık (sadece bir kerelik)
pip install PySide6

# Sihirbazı aç (parametrelerle veya boş)
metraj wizard --cad proje.dxf --reference referans.xlsx -o proje_profile.yaml
```

5 adımı sırayla tamamla → `proje_profile.yaml` hazır. Sonra:

```bash
metraj run --mode structural --structural-config proje_profile.yaml proje.dxf -o build/
```

---

## Önkoşullar

| Gereksinim | Notlar |
|---|---|
| **CAD dosyası** | `.dwg` veya `.dxf`. DWG için ODA File Converter kurulu olmalı (`metraj diagnose`). |
| **Referans Excel** | Kumluca tarzı (`A KALIP` + `A BETON` sayfaları). Diğer layoutlar için `comparison_label_aliases` YAML manuel girişi gerekebilir. |
| **PySide6** | `pip install PySide6` veya `pip install metraj[gui]`. |

---

## 5 Adım

### Adım 1 / 5 — Dosya seçimi

3 yol girilir:
1. **CAD (DWG/DXF)** — yapısal çizim. Gözat butonuyla dosya seçici.
2. **Referans Excel** — firmanın elle hazırladığı metraj tablosu (KALIP m², BETON m³).
3. **Çıktı YAML** — sihirbaz sonunda yazılacak profil dosyası (default: `profile.yaml`).

**"Sonraki"** ile geç. Dosyalar yoksa uyarı verir.

### Adım 2 / 5 — Profil fit

Arka planda (QThread) çalışan saf-geometri pipeline (~10-20 saniye):
- DXF parse
- Yapısal eleman çıkarımı
- `calculate(smodel, CalcParams())` baseline raporu
- Reference Excel ile karşılaştırma → `target / baseline` = fitted scale (her alan için)
- **2. aşama**: kat-bazlı `doseme_*`, `beam_*`, `parapet_formwork_floor_scale` dict'leri (varyans > %3 ise)

İlerleme `QProgressBar` (indeterminate) + log `QTextEdit`'te görünür. Bitince **"Sonraki"** aktif olur.

Örnek çıktı:
```
Baseline KALIP toplam: 7181.72 m2
Referans KALIP toplam: 4281.49 m2
column_concrete_section_fraction: 0.4998 (baseline=333.73, ref=166.81, matched_rows=6)
slab_net_area_fraction: 0.5078 (baseline=3458.00, ref=1756.06, matched_rows=41)
...
doseme_net_scale_by_floor_label: {0,00=1.043, +2,85=1.045, ...}
```

### Adım 3 / 5 — Manuel ince ayar

Tabloda **9 global scale** değeri (`QDoubleSpinBox` ile düzenlenebilir):

| CalcParams alanı | Fitted scale | Baseline toplam | Referans toplam | Satır sayısı |
|---|---:|---:|---:|---:|
| column_concrete_section_fraction | 0.4998 | 333.73 | 166.81 | 6 |
| slab_net_area_fraction | 0.5078 | 3458.00 | 1756.06 | 42 |
| ... | ... | ... | ... | ... |

İsteğe bağlı: kullanıcı `beam_formwork_length_fraction` gibi alanları **manuel** düzenler. Tablodaki dict alanlar (`doseme_net_scale_by_floor_label`) Step 5'te YAML'a aynen yazılır, sihirbaz tek-yere ayrı dialog değildir — manual ince ayar isteyen YAML çıktısını düzenler.

### Adım 4 / 5 — Test koştur

**"Pipeline test koştur"** butonu, fit edilen + kullanıcı düzenlenmiş `CalcParams` ile pipeline'ı çalıştırır (~10 sn). Sapma metrikleri:

| Metrik | Anlam |
|---|---|
| KALIP toplam (m²) | Hesaplanan kalıp toplamı |
| BETON toplam (m³) | Hesaplanan beton toplamı |
| KALIP toplam sapma | `\|hesap-ref\| / ref` |
| BETON toplam sapma | aynı |
| Satır-bazı MAX KALIP sapma | En büyük tek-satır sapma % (uyarı eşiği genelde %1) |
| Satır-bazı MAX BETON sapma | aynı |

**İyi değerler:** toplam sapma <%5, max satır <%50.
**Çok yüksek (>%50)?** Adım 3'e dönüp ilgili scale'i manuel düzelt.

### Adım 5 / 5 — Kaydet ve kapat

Önizleme:
```yaml
project_name: Wizard (proje_adı)
excel_layout: kumluca
compare_to_reference: true
validation_tolerance: 0.01
params:
  column_concrete_section_fraction: 0.4998
  slab_net_area_fraction: 0.5078
  doseme_net_scale_by_floor_label:
    "0,00": 1.043
    "+2,85": 1.045
    ...
reference_excel_path: ../ornekRef/referans.xlsx
```

**"Kaydet ve Kapat"** → YAML diske yazılır, sihirbaz kapanır.

---

## CLI alternatifi (GUI olmadan)

Sihirbazın yaptığı her şeyi CLI ile yapabilirsin:

```bash
metraj structural-fit proje.dxf referans.xlsx -o profile.yaml
# Aynı 30 katsayıyı YAML'a yazar; manuel ince ayar `nano profile.yaml`.

metraj run --mode structural --structural-config profile.yaml proje.dxf -o build/
# Sapma raporunu build/dogrulama_ozeti.txt'te oku.
```

CLI vs GUI karşılaştırma:

| Adım | GUI (`wizard`) | CLI (`structural-fit`) |
|---|---|---|
| Dosya seçimi | QFileDialog | argümanlar |
| Fit | Otomatik | Otomatik |
| Manuel ince ayar | `QDoubleSpinBox` her satır | `nano profile.yaml` |
| Test | "Pipeline test koştur" butonu | `metraj run ...` |
| Kaydet | "Kaydet ve Kapat" | Dosya zaten yazıldı |

---

## Bilinen sınırlamalar

1. **BETON sapma single-param ile %9 plato.**
   Auto-fit KALIP toplamında elle-yazılı Kumluca yaml'ı geçer (%0.23 < %0.48), ama BETON'da `beam_split_*` ailesi (multi-kat plan kiriş bölünmesi) tek-param fit edilemiyor. Bu nedenle BETON toplam sapma ~%9 kalır. Bunu düşürmek için:
   - Manuel `beam_split_*` parametrelerini YAML'a ekle (uzman bilgisi gerek)
   - 5+ proje birikince `metraj train-profiles` ile median kullan
2. **Sadece "kumluca" excel layout.** `A KALIP` + `A BETON` sayfalı Kumluca format hard-coded. Farklı format için ileride `generic_writer` gelecek.
3. **PySide6 zorunlu.** GUI'siz ortamda CLI yolunu kullan.
4. **Aynı CAD'i iki kez çalıştırır.** Fit (Adım 2) + Test (Adım 4) iki ayrı pipeline; ~30 saniyelik DXF için 60 sn. Faz 7+ optimize edilebilir.

---

## Sonraki adımlar — UI'dan sonrası

| Senaryo | Komut |
|---|---|
| Sihirbazda otomatik bulunamayan katmanı manuel atama | `metraj structural-feedback set-layer-kind feedback.json "K-X" column` |
| Birden fazla projeyle median profile | `metraj train-profiles --pairs cad1,ref1 --pairs cad2,ref2 -o default.yaml` |
| Tüm firma projelerinden global signal_hints | `metraj structural-feedback global-hints ./feedbacks/ -o hints.yaml` |
| Profile karşılaştırma | `metraj structural-compare proje.dxf --config v1.yaml --config v2.yaml -o build/cmp` |

---

## Sorun giderme

**"PySide6 yuklu degil" hatası**
```bash
pip install PySide6
# veya:
pip install "metraj[gui]"
```

**Fit takılıp kaldı**
DXF çok büyükse (148 MB Kumluca DXF gibi) DXF parse ~10 saniye, ardından elem dedupe ~5 saniye. 60 saniyeden uzun sürerse `Iptal` butonu.

**"Cikti YAML yazilamadi"**
Klasörün yazma izni var mı? `chmod` ile düzelt veya `--output` ile farklı yere ver.

**Sapma çok yüksek (KALIP > %30)**
Muhtemelen:
- Yanlış excel_layout (Kumluca olmayan format)
- Yapısal katmanlar autodetect tarafından bulunamamış → önce `metraj inventory proje.dxf --autodetect-layers --json` ile envanteri kontrol et
- INSERT-bazlı kolonlar var → `structural_layer_include_kind` yaml'da explicit
