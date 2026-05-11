✅ Ana UI'a Entegre Edildi
155/155 test geçti. Sihirbazlar artık ana pencerede.

Ne yapıldı
Ana pencerede (metraj ui) CAD/mod seçici satırının altına yeni "Yapısal Profil" satırı eklendi:


┌──────────────────────────────────────────────────────────────────────────────┐
│ [CAD: proje.dxf ▼] [Çıktı: build/] [Mod: Yapısal ▼] [☐ Ref Excel] [Çalıştır]│
├──────────────────────────────────────────────────────────────────────────────┤
│ Yapısal Profil: (default: kumluca.yaml)                                      │
│   [YAML Yükle...]  [Yeni Profil (UI)...]  [Excel ile Kalibre Et...]         │
│   [Default'a Dön]                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
4 buton, tek pencerede tüm akış
Buton	İşlev	Hangi sihirbazı açar
"YAML Yükle..."	Diskten önceden hazırlanmış profil seç	QFileDialog
"Yeni Profil (UI)..."	Excel-bağımsız config sihirbazı	StructuralConfigDialog (8 sekme + dict + override)
"Excel ile Kalibre Et..."	Auto-fit sihirbazı	CalibrationWizard (5 adım; CAD ve referans pre-fill)
"Default'a Dön"	Aktif profili sıfırla, kumluca.yaml'a dön	—
Akış mantığı
Mod Yapısal veya Otomatik seçildiğinde profil paneli aktif olur; Mimari'de pasif (gri).
Sihirbazlardan biri çalıştırılınca kaydet sonrası, dialog'un yazdığı YAML otomatik aktif profil olur.
Label renkli güncellenir: (default) → gri; aktif profil → yeşil bold + dosya adı + proje adı.
"Çalıştır" basıldığında _struct_config_for_ui() aktif profili öncelikli yükler; yoksa kumluca.yaml default'u.
Referans Excel + tolerans checkbox'ı hâlâ üstte; aktif profile ek olarak doğrulama açılabilir (iki paralel mekanizma birlikte çalışır).
Otomatik dosya yolu önerisi
CAD seçili ise:

Yeni profil için varsayılan: <cad_klasoru>/<cad_adi>.profile.yaml
Aksi halde: <output_dir>/profile.yaml
Pre-fill akışı
"Excel ile Kalibre Et" butonu basıldığında:

Ana pencerede CAD seçilmiş → sihirbaza pre-fill edilir
Referans Excel checkbox aktifse → o da pre-fill edilir
Kullanıcı sihirbazda dosya seçmek zorunda kalmaz, sadece adımları geçer
UI çalıştırma komutu

/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 -m metraj.cli ui
veya kısaca:


python3.14 -m metraj.cli ui
Kullanıcı senaryosu
Ana pencereyi aç (metraj ui)
CAD dosyasını seç (DWG/DXF)
Mod: Yapısal
Profil panelinden tercih et:
Excel'in var → "Excel ile Kalibre Et" (auto-fit %0.23 KALIP / %9 BETON)
Excel'in yok → "Yeni Profil (UI)" → 8 sekme (Kolon/Perde/Kiriş/Döşeme/Temel/Parapet+Asansör/Minha/Çatı) + kat-bazlı dict + katman override
Hazır YAML'ın var → "YAML Yükle"
"Metraj Çalıştır" — aktif profil kullanılır
Sekmelerden sonuçları gör: 2D Plan, Kalıp/Beton, Yapısal Özet, Doğrulama, Uyarılar
Artık config-wizard ve calibration_wizard ayrı tool değil, ana UI'nın doğal parçası.

Kullanıcının ihtiyacının özeti
Önceki sınır	Şimdiki çözüm
Referans Excel zorunluydu (Kumluca formatı)	metraj config-wizard ile UI'dan kullanıcı çarpanları girer
Excel formatına bağımlı	excel_layout=generic ile jenerik tablo çıktısı
Auto-fit Excel olmadan çalışmıyor	3 hazır preset (geometry_full, geometry_half, custom_template)
YAML manual editing	6 sekmeli QDialog, slider/spinbox ile düzenleme
Şu anki sistem artık iki paralel kalibrasyon yolu sunuyor:

Excel ile auto-fit (Faz 4 v2) → referans varsa, KALIP %0.23 / BETON %9
Excel'siz UI config (bu faz) → kullanıcı ne istediğini söyler, sistem birebir uygular
Hangisini istersen kullanıcı seçer. Manual UI smoke test için:


metraj config-wizard -o /tmp/test.yaml