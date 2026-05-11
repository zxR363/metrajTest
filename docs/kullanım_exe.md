2. UI komutu
Ana pencereyi açmak için:


/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 -m metraj.cli ui
veya kısaltma (path'in PATH'inde varsa):


python3.14 -m metraj.cli ui
Ana pencerede neler var:

DWG/DXF dosya seçici
Çıkış klasörü seçici
Mod seçimi: {Otomatik, Mimari, Yapısal}
Çalıştır butonu
9 sekme:
2D Plan — duvar/mahal/açıklık görüntüleyici
Mahal Listesi — kat, kod, ad, alan, çevre, yükseklik, kapı/pencere sayısı
Açıklıklar — kapı/pencere tablosu
İcmal — Poz aggregation
Yapısal Özet — HTML tablo (kat dağılımı, eleman sayıları)
Kalıp/Beton — yapısal sonuçlar (m², m³)
Yapısal Katmanlar — manuel layer kind override
Doğrulama — hesap vs GT (renk kodlu: yeşil OK, kırmızı eşik üstü)
Uyarılar — autodetect unmatched + config gaps
Sihirbazlar (yardımcı GUI'ler)

# 1. Excel ile auto-fit (Faz 4)
python3.14 -m metraj.cli wizard --cad proje.dxf --reference ref.xlsx -o profile.yaml

# 2. Excel-bağımsız: kullanıcı UI'dan çarpan girer (yeni eklenti)
python3.14 -m metraj.cli config-wizard -o profile.yaml

# 3. GUI'siz: hızlı preset
python3.14 -m metraj.cli config-wizard --preset geometry_full --preset-only -o saf.yaml
Tipik kullanım (kullanıcı senaryosu)

# Excel'i yok: UI'dan çarpan ayarla
python3.14 -m metraj.cli config-wizard -o /tmp/proje1.yaml

# Profili ana pencerede uygula veya CLI'den koştur
python3.14 -m metraj.cli run --mode structural --structural-config /tmp/proje1.yaml proje.dxf -o build/

# Ya da ana pencereden GUI ile her şeyi yap (DWG seç + Çalıştır)
python3.14 -m metraj.cli ui
Bir ek not: metraj ui komutunda --config parametresinin eksik olduğunu fark ettim ve düzelttim — varsayılan olarak metraj/config klasörünü kullanır, kullanıcı isterse --config /başka/klasör ile override edebilir.



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