"""Kullanim Klavuzu PDF uretici.

Komut satirindan:

    python -m metraj.scripts.build_user_guide docs/Metraj_Kullanim_Klavuzu.pdf

ReportLab ile cok sayfali, baslikli, kod blokli, tablolu bir kullanim
dokumani uretir.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "Title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=24, leading=30, textColor=colors.HexColor("#1F3864"),
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=12,
            textColor=colors.HexColor("#404040"), spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=colors.HexColor("#1F3864"),
            spaceBefore=18, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=14, leading=18, textColor=colors.HexColor("#2E5395"),
            spaceBefore=14, spaceAfter=8,
        ),
        "h3": ParagraphStyle(
            "H3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=12, leading=16, textColor=colors.HexColor("#000000"),
            spaceBefore=10, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=10, leading=14,
            spaceAfter=6, alignment=TA_JUSTIFY,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["Normal"], fontSize=10, leading=14,
            leftIndent=14, bulletIndent=4, spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "Code", parent=base["Code"], fontName="Courier",
            fontSize=9, leading=12, leftIndent=8, rightIndent=8,
            backColor=colors.HexColor("#F2F2F2"),
            borderColor=colors.HexColor("#CCCCCC"), borderWidth=0.5,
            borderPadding=6, spaceBefore=4, spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "Caption", parent=base["Normal"], fontSize=8,
            textColor=colors.HexColor("#606060"), spaceAfter=10,
        ),
        "tip": ParagraphStyle(
            "Tip", parent=base["Normal"], fontSize=10, leading=14,
            backColor=colors.HexColor("#FFF7E6"), textColor=colors.HexColor("#5C3D00"),
            borderColor=colors.HexColor("#FFB266"), borderWidth=0.5,
            borderPadding=6, spaceBefore=4, spaceAfter=10,
        ),
    }
    return styles


def _kv_table(rows, col_widths=(5 * cm, 11.5 * cm)):
    t = Table(rows, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F2F2F2")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _page_chrome(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#808080"))
    canvas.drawString(2 * cm, 1 * cm, "Metraj Otomasyon Araci - Kullanim Klavuzu")
    canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"Sayfa {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#1F3864"))
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, 1.3 * cm, A4[0] - 2 * cm, 1.3 * cm)
    canvas.restoreState()


def build(out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = _styles()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Metraj Otomasyon Araci - Kullanim Klavuzu",
        author="Metraj",
    )

    story = []

    # ====== KAPAK ======
    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("Metraj Otomasyon Araci", s["title"]))
    story.append(Paragraph("AutoCAD DWG/DXF Tabanli Mimari Metraj Otomasyonu",
                            s["subtitle"]))
    story.append(Paragraph("Kullanim Klavuzu", s["h1"]))
    story.append(Spacer(1, 1 * cm))
    story.append(_kv_table([
        ["Surum", "0.1.0"],
        ["Yayim Tarihi", datetime.now().strftime("%Y-%m-%d")],
        ["Hedef Kitle", "Insaat firmalari, kesfi cikartan mimar/insaat muhendisi/teknisyenler"],
        ["On Kosullar", "Python 3.10+, ODA File Converter (DWG icin), pip"],
    ]))
    story.append(PageBreak())

    # ====== ICINDEKILER ======
    story.append(Paragraph("Icindekiler", s["h1"]))
    toc_rows = [
        ["1.", "Sistem Tanitimi"],
        ["2.", "Kurulum"],
        ["3.", "Hizli Baslangic"],
        ["4.", "Komut Satiri Kullanimi (CLI)"],
        ["5.", "Grafiksel Arayuz (PySide6 GUI)"],
        ["6.", "Yeni Bir Proje Icin Kurulum"],
        ["7.", "Konfigurasyon Dosyalari"],
        ["8.", "Cikti Dosyalari"],
        ["9.", "Sik Karsilasilan Sorunlar"],
        ["10.", "SSS"],
    ]
    toc_table = Table(toc_rows, colWidths=[1.5 * cm, 14 * cm])
    toc_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(toc_table)
    story.append(PageBreak())

    # ====== 1. SISTEM TANITIMI ======
    story.append(Paragraph("1. Sistem Tanitimi", s["h1"]))
    story.append(Paragraph(
        "Metraj Otomasyon Araci, mimari AutoCAD cizimlerinden mahal listesi, "
        "kapi/pencere dograma metraji, duvar/kabuk imalat metraji ve poz "
        "icmalini <b>otomatik</b> cikartan bagimsiz bir masaustu uygulamasidir. "
        "AutoCAD lisansi gerektirmez; DWG dosyalari icin yalnizca ucretsiz "
        "ODA File Converter kullanilir; DXF dosyalari dogrudan kabul edilir.",
        s["body"]))
    story.append(Paragraph("Pipeline (Veri Akisi)", s["h2"]))
    story.append(_kv_table([
        ["Adim", "Aciklama"],
        ["1. CAD Yukle", "DWG/DXF dosyasi okunur (ezdxf), birim normallestirilir."],
        ["2. Katman Eslesme",
         "Otomatik 'autodetect' veya manuel layer_map.yaml ile katmanlar "
         "rolllere baglanir (wall/door/window/room_label ...)."],
        ["3. Mahal Tespiti",
         "3 fallback strateji: kapali polyline > duvar polygonize > inverse-hatch."],
        ["4. Aciklik Tespiti",
         "Kapi/pencere bloklari + dynamic block parametrelerinden tip/en/yukseklik."],
        ["5. Net Metraj",
         "Alan, cevre, yukseklik, kapi/pencere minhasi - net doseme/duvar/tavan/supurgelik."],
        ["6. Tip Atama",
         "Mahal adina + TipDefinitions konfigine gore D1/W1/T1 ya da "
         "DS3/DV7/TV2 ... atanir."],
        ["7. Icmal",
         "Tip basina poz dagilimi, kategori toplamlari, birim fiyat x miktar."],
        ["8. Cikti",
         "Excel (Mahal/minha/Icmal sayfalari) + PDF kategori ozet raporu."],
    ], col_widths=(4 * cm, 12.5 * cm)))
    story.append(PageBreak())

    # ====== 2. KURULUM ======
    story.append(Paragraph("2. Kurulum", s["h1"]))
    story.append(Paragraph("2.1 Python ve bagimliliklar", s["h2"]))
    story.append(Paragraph(
        "Python 3.10 veya ustu gerekir.  Sistemde python yoksa "
        "<b>python.org</b> uzerinden kurun.",
        s["body"]))
    story.append(Paragraph(
        "Proje klasorunde:", s["body"]))
    story.append(Paragraph(
        "<font face='Courier'>pip install -r requirements.txt</font><br/>"
        "<font face='Courier'># veya:</font><br/>"
        "<font face='Courier'>pip install -e .[gui,dev]</font>",
        s["code"]))
    story.append(Paragraph("2.2 PySide6 (GUI icin)", s["h2"]))
    story.append(Paragraph(
        "Komut satirini kullanmaya niyetli degilseniz GUI tarafini ayrica "
        "yuklemek gerekir:",
        s["body"]))
    story.append(Paragraph(
        "<font face='Courier'>pip install --user PySide6</font>",
        s["code"]))
    story.append(Paragraph("2.3 ODA File Converter (DWG icin)", s["h2"]))
    story.append(Paragraph(
        "Sadece DWG dosyalariyla calisacaksaniz ODA File Converter kurun:",
        s["body"]))
    story.append(Paragraph(
        "<a color='#1F3864' href='https://www.opendesign.com/guestfiles/oda_file_converter'>"
        "https://www.opendesign.com/guestfiles/oda_file_converter</a>",
        s["body"]))
    story.append(Paragraph(
        "Yuklu degilse: AutoCAD/BricsCAD'den DWG'yi <b>SAVE AS &gt; DXF</b> "
        "ile cikartip dogrudan DXF kullanabilirsiniz (ODA gereksizdir).",
        s["tip"]))
    story.append(PageBreak())

    # ====== 3. HIZLI BASLANGIC ======
    story.append(Paragraph("3. Hizli Baslangic", s["h1"]))
    story.append(Paragraph("Default ayarlarla en hizli yol:", s["body"]))
    story.append(Paragraph(
        "<font face='Courier'># DXF dosyasi varsa dogrudan calistirin:</font><br/>"
        "<font face='Courier'>python -m metraj.cli run path/to/proje.dxf -o build/</font>",
        s["code"]))
    story.append(Paragraph(
        "Cikti olarak <b>build/metraj.xlsx</b> ve <b>build/metraj.pdf</b> "
        "olusur. Excel'de 3 sayfa var:", s["body"]))
    story.append(Paragraph("- Kutuphane MAHAL: tum mahallerin listesi", s["bullet"]))
    story.append(Paragraph("- minha: kapi/pencere dusumleri (kat x olcu x adet)", s["bullet"]))
    story.append(Paragraph("- Icmal: kategori bazli poz toplamlari ve tutar", s["bullet"]))
    story.append(Paragraph("3.1 Hizli baslangic adimlari", s["h2"]))
    quick_steps = [
        ["#", "Komut", "Aciklama"],
        ["1", "python -m metraj.cli inventory <dxf>",
         "Cizimdeki katman ve blok envanterini cikarir"],
        ["2", "python -m metraj.cli run <dxf> -o build/",
         "Tam pipeline: mahal + minha + icmal + Excel + PDF"],
        ["3", "python -m metraj.cli ui",
         "Grafiksel arayuzu baslatir"],
    ]
    qst = Table(quick_steps, colWidths=(1 * cm, 8 * cm, 7 * cm))
    qst.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F2F2F2")]),
        ("FONTNAME", (1, 1), (1, -1), "Courier"),
    ]))
    story.append(qst)
    story.append(PageBreak())

    # ====== 4. CLI ======
    story.append(Paragraph("4. Komut Satiri Kullanimi (CLI)", s["h1"]))
    story.append(Paragraph(
        "Tum CLI komutlari su sablona uyar:", s["body"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli [GLOBAL] &lt;komut&gt; [komut-secenekleri]</font>",
        s["code"]))
    story.append(Paragraph("Global secenekler:", s["body"]))
    story.append(_kv_table([
        ["Secenek", "Aciklama"],
        ["--config &lt;klasor&gt;", "Konfigurasyon klasoru (default: dahili 'metraj/config')"],
        ["--oda &lt;yol&gt;", "ODA File Converter binary yolu (otomatik bulunamadiysa)"],
        ["-v / --verbose", "Detayli loglama"],
    ]))

    story.append(Paragraph("4.1 inventory - Katman/blok envanteri", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli inventory PROJE.dxf [--json out.json] "
        "[--autodetect-layers] [--write-layer-map yol/layer_map.yaml]</font>",
        s["code"]))
    story.append(Paragraph(
        "Cizimde bulunan tum katmanlari, herbirinde kac entity oldugunu, "
        "blok tanimlari ve kullanim sayilarini listeler. <b>--autodetect-layers</b> "
        "ile katman isimlerinden role'leri (wall/door/window/...) heuristikle "
        "tahmin eder; <b>--write-layer-map</b> ile bu tahminleri YAML olarak yazar.",
        s["body"]))

    story.append(Paragraph("4.2 run - Tam pipeline", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli run PROJE.dxf -o build/ [--no-pdf] "
        "[--no-excel] [--no-autodetect]</font>",
        s["code"]))
    story.append(Paragraph(
        "Mahal + aciklik + duvar tespiti + net metraj + icmal + Excel/PDF rapor."
        " <b>--no-autodetect</b> ile katman tahmini devre disi.",
        s["body"]))

    story.append(Paragraph("4.3 new-project - Yeni proje konfigurasyonu", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli new-project ./projeler/x "
        "[--proje-adi 'Adi'] [--force]</font>",
        s["code"]))
    story.append(Paragraph(
        "Sablon konfig dosyalarini (layer_map, poz_library, tip_definitions, "
        "project) yeni klasore kopyalar. Sonra <b>--config</b> ile bu klasoru "
        "kullanarak run komutu calistirilir.",
        s["body"]))

    story.append(Paragraph("4.4 compare - Mevcut Excel ile karsilastirma", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli compare PROJE.dxf "
        "MEVCUT_METRAJ.xlsx</font>",
        s["code"]))
    story.append(Paragraph(
        "Pipeline ciktisini, firmanin elle hazirlamis oldugu Excel ile mahal "
        "bazinda karsilastirir; alan/cevre sapmalarini buyukluk sirasiyla yazar. "
        "Faz 0 PoC dogrulamasi icin idealdir.",
        s["body"]))

    story.append(Paragraph("4.5 ui - Grafiksel arayuz", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli ui</font>",
        s["code"]))
    story.append(Paragraph(
        "PySide6 main window'u baslatir.  Detay icin Bolum 5.",
        s["body"]))
    story.append(PageBreak())

    # ====== 5. UI ======
    story.append(Paragraph("5. Grafiksel Arayuz (PySide6 GUI)", s["h1"]))
    story.append(Paragraph("5.1 Baslatma", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>pip install --user PySide6   # bir defalik kurulum</font><br/>"
        "<font face='Courier'>python -m metraj.cli ui</font>",
        s["code"]))
    story.append(Paragraph(
        "Alternatif (varsayilan dahili konfig disinda bir konfigle):",
        s["body"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli --config /yol/proje_konfig ui</font>",
        s["code"]))

    story.append(Paragraph("5.2 Arayuz Yerlesimi", s["h2"]))
    story.append(_kv_table([
        ["Eleman", "Islev"],
        ["Ust Cubuk: 'DWG/DXF Sec...'",
         "Cizim dosyasini secer; secildiginde dosya adi gorunur."],
        ["Ust Cubuk: 'Cikti Klasoru...'",
         "Excel + PDF raporlarinin yazilacagi klasor."],
        ["Ust Cubuk: 'Metraji Calistir'",
         "Pipeline'i arka planda (QThread) baslatir; UI donmaz."],
        ["Sekme: '2D Plan'",
         "QGraphicsView; duvarlar (siyah), mahaller (mavi dolgu + kod/ad), "
         "kapi/pencere (kirmizi nokta) gosterilir.  Mouse drag ile pan, "
         "scroll ile zoom (Qt default)."],
        ["Sekme: 'Mahal Listesi'",
         "Tum mahallerin tablosu: kod, ad, tipler, alan/cevre/yukseklik, "
         "net metrajlar, kapi/pencere adetleri."],
        ["Sekme: 'Acikliklar'",
         "Kapi/pencere listesi: kat, tur, mahal, en, yukseklik, blok adi."],
        ["Sekme: 'Icmal'",
         "Tum poz kalemleri: kategori, poz no, tanim, miktar, birim fiyat, tutar."],
        ["Sekme: 'Uyarilar'",
         "Eslesmemis katmanlar, tip atanmamis mahaller, mahale eslesmemis "
         "acikliklar."],
        ["Status Bar",
         "Pipeline durumu: 'calisiyor / tamam / hata' + mahal/aciklik sayilari "
         "+ genel toplam tutar."],
    ]))

    story.append(Paragraph("5.3 Tipik kullanim", s["h2"]))
    story.append(Paragraph("1. <b>'DWG/DXF Sec'</b> butonuyla dosyanizi secin.", s["bullet"]))
    story.append(Paragraph("2. <b>'Cikti Klasoru'</b> butonuyla raporlarin yazilacagi yeri belirleyin.", s["bullet"]))
    story.append(Paragraph("3. <b>'Metraji Calistir'</b>'a basin; alt status bar 'pipeline calisiyor' diyecek.", s["bullet"]))
    story.append(Paragraph("4. Bittiginde tablolar dolar; <b>'2D Plan'</b> sekmesinde mahal renklendirmesini gorebilirsiniz.", s["bullet"]))
    story.append(Paragraph("5. <b>'Uyarilar'</b> sekmesini mutlaka kontrol edin: eslesmemis katman varsa konfig duzeltmesi gerekir.", s["bullet"]))
    story.append(Paragraph(
        "PoC asamasinda hala excel/pdf yazimi sirasinda manuel duzeltme yapmak isteyebilirsiniz; "
        "tablolari Excel'e kopyalayip kontrol etmek bunu kolaylastirir.",
        s["tip"]))
    story.append(PageBreak())

    # ====== 6. YENI PROJE ======
    story.append(Paragraph("6. Yeni Bir Proje Icin Kurulum", s["h1"]))
    story.append(Paragraph(
        "Sistem tamamen <b>proje-agnostiktir</b>. Yeni bir proje icin tek "
        "seferlik 3 adim yeterli:", s["body"]))
    story.append(Paragraph("Adim 1 - Proje konfigurasyonu olustur", s["h3"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli new-project ./projeler/yeni_proje "
        "--proje-adi 'X Insaat - Konut Projesi'</font>",
        s["code"]))
    story.append(Paragraph(
        "Bu komut <b>./projeler/yeni_proje/</b> klasoru icine 4 dosya kopyalar:",
        s["body"]))
    story.append(Paragraph("- layer_map.yaml (genis Turk + AIA katman listesi)", s["bullet"]))
    story.append(Paragraph("- poz_library.yaml (11 jenerik poz)", s["bullet"]))
    story.append(Paragraph("- tip_definitions.yaml (D1/W1/T1/S1 jenerik tip kodlari)", s["bullet"]))
    story.append(Paragraph("- project.yaml (kat semasi: Z/1/2)", s["bullet"]))

    story.append(Paragraph("Adim 2 - Cizimi analiz et + katman_map'i guncelle", s["h3"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli inventory --autodetect-layers \\<br/>"
        "    --write-layer-map ./projeler/yeni_proje/layer_map.yaml \\<br/>"
        "    proje.dxf</font>",
        s["code"]))
    story.append(Paragraph(
        "Sistem cizimdeki katmanlari (orn. T-DUVAR, A-WALL, M-KAPI, ...) "
        "heuristikle role'lere baglar ve YAML'a yazar. Eslesmeyenleri "
        "'unmatched_layers' altinda raporlar; bunlari manuel ekleyebilirsiniz.",
        s["body"]))

    story.append(Paragraph("Adim 3 - Pipeline'i calistir", s["h3"]))
    story.append(Paragraph(
        "<font face='Courier'>python -m metraj.cli --config ./projeler/yeni_proje "
        "run proje.dxf -o build/</font>",
        s["code"]))
    story.append(Paragraph(
        "Cikti CLI'da: mahal sayisi, aciklik sayisi, icmal poz sayisi, "
        "genel toplam (TL).  Ayrica <b>build/metraj.xlsx</b> ve "
        "<b>build/metraj.pdf</b> uretilir.",
        s["body"]))

    story.append(Paragraph(
        "Eger firmaniz farkli tip kodlari (orn. DS1..DS6, Z1..Z4, ZD1..ZD9) "
        "kullaniyorsa, <b>tip_definitions.yaml</b>'i bir kez bunlarla "
        "doldurursunuz; gelecek tum projelerde bu klasoru kopyalayip "
        "kullanabilirsiniz.",
        s["tip"]))
    story.append(PageBreak())

    # ====== 7. KONFIGURASYON ======
    story.append(Paragraph("7. Konfigurasyon Dosyalari", s["h1"]))
    story.append(Paragraph("7.1 layer_map.yaml - Katman -> Rol", s["h2"]))
    story.append(Paragraph(
        "Cizimdeki AutoCAD katmanlarinin hangi anlami tasidigini belirler. "
        "Wildcard (* ile biten) destekli.",
        s["body"]))
    story.append(Paragraph(
        "<font face='Courier'>roles:<br/>"
        "&nbsp;&nbsp;wall:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;layers: [A-WALL, DUVAR, T-DUVAR]<br/>"
        "&nbsp;&nbsp;door:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;layers: [A-DOOR, KAPI, T-KAPI]<br/>"
        "&nbsp;&nbsp;room_label:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;layers: [A-AREA-IDEN, MAHAL-ETIKET]<br/>"
        "</font>",
        s["code"]))

    story.append(Paragraph("7.2 poz_library.yaml - Poz katalogu", s["h2"]))
    story.append(Paragraph(
        "Cevre, Sehircilik ve Iklim Degisikligi Bakanligi formati: poz no, "
        "kategori, tanim, birim, birim fiyat.",
        s["body"]))
    story.append(Paragraph(
        "<font face='Courier'>pozlar:<br/>"
        '&nbsp;&nbsp;"15.385.1028":<br/>'
        "&nbsp;&nbsp;&nbsp;&nbsp;kategori: DOSEME<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;tanim: 60x60 Renkli Sirli Porselen Karo<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;birim: m2<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;birim_fiyat: 720.0<br/>"
        "</font>",
        s["code"]))

    story.append(Paragraph("7.3 tip_definitions.yaml - Tip kodu recetesi", s["h2"]))
    story.append(Paragraph(
        "Mahal tip kodlari: bir mahalde hangi pozlarin ne yuzde ile "
        "uygulanacagini belirtir. <b>pay</b> 0..1 arasi, 1 mahalde 2 farkli "
        "kaplama varsa toplami 1.0'dan az olabilir.",
        s["body"]))
    story.append(Paragraph(
        "<font face='Courier'>tipler:<br/>"
        "&nbsp;&nbsp;D1:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;kategori: DOSEME<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;tanim: 60x60 porselen karo<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;pozlar:<br/>"
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;- {poz_no: "15.385.1028", pay: 1.0}<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;- {poz_no: "15.250.1011", pay: 1.0}<br/>'
        "</font>",
        s["code"]))

    story.append(Paragraph("7.4 project.yaml - Proje seviyesi ayarlar", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>proje_adi: 'X Konut Projesi'<br/>"
        "katlar:<br/>"
        '&nbsp;&nbsp;- {kod: "B", ad: "Bodrum", kot_alt: -8.0, kot_ust: -3.5}<br/>'
        '&nbsp;&nbsp;- {kod: "Z", ad: "Zemin", kot_alt: -0.5, kot_ust: 4.0}<br/>'
        "duvar_yukseklik_bantlari: [0.10, 0.15, 0.20, 0.30]<br/>"
        "kapi_yuvarlama_cm: 5.0<br/>"
        "pencere_yuvarlama_cm: 5.0<br/>"
        "</font>",
        s["code"]))
    story.append(PageBreak())

    # ====== 8. CIKTILAR ======
    story.append(Paragraph("8. Cikti Dosyalari", s["h1"]))
    story.append(Paragraph("8.1 Excel: build/metraj.xlsx", s["h2"]))
    story.append(_kv_table([
        ["Sayfa", "Icerik"],
        ["Kutuphane MAHAL",
         "Tum mahaller; her satirda tip kodlari, alan, cevre, yukseklik, "
         "minha degerleri ve net metrajlar.  En altta GENEL TOPLAM satiri "
         "formul ile hesaplanir."],
        ["minha",
         "Kapi ve pencerelerin kat x olcu x adet kirilimi.  TOPLAM (m2) "
         "alani da formul ile gelir."],
        ["Icmal",
         "Kategori (DOSEME/DUVAR/TAVAN/SUPURGELIK/DOGRAMA/KABUK) altlarinda "
         "her poz icin miktar, birim fiyat, tutar.  Her kategori sonunda "
         "ARA TOPLAM, en altta GENEL TOPLAM (TL)."],
    ]))

    story.append(Paragraph("8.2 PDF: build/metraj.pdf (proje ozeti)", s["h2"]))
    story.append(Paragraph(
        "A4 1 sayfa kesfi ozeti: mahal sayisi, toplam alan, kategori "
        "tutarlari, en yuksek 10 poz tablosu.  Yonetime sunum icin uygundur.",
        s["body"]))

    story.append(Paragraph("8.3 Konfig boslugu uyarilari", s["h2"]))
    story.append(Paragraph(
        "Pipeline calistirildiginda console'a yansiyan uyarilar (ayni "
        "zamanda PipelineResult.config_gaps icinde yapisal halde):",
        s["body"]))
    story.append(Paragraph("- 'Tanimsiz tip kodlari (X): D9, W11': bu kodlar tip_definitions.yaml'a eklenmeli.", s["bullet"]))
    story.append(Paragraph("- 'Tanimsiz poz numaralari (X): 15.385.1099': poz_library.yaml'a eklenmeli.", s["bullet"]))
    story.append(Paragraph("- 'Eslesmemis katman': layer_map.yaml'a eklenmeli ya da inventory --autodetect-layers ile guncellenmeli.", s["bullet"]))
    story.append(PageBreak())

    # ====== 9. SIK SORUNLAR ======
    story.append(Paragraph("9. Sik Karsilasilan Sorunlar", s["h1"]))
    story.append(_kv_table([
        ["Sorun", "Cozum"],
        ["ODA File Converter not found",
         "DWG yerine DXF kullan ya da ODA'yi indir/kur (bkz. 2.3). "
         "Kurduysan --oda /yol/binary ile elle gosterebilirsin."],
        ["PySide6 yuklu degil hatasi",
         "pip install --user PySide6 ile yukle. Daha sonra 'python -m metraj.cli ui'."],
        ["Mahal sinirlari tespit edilemedi (0 mahal)",
         "Cizimdeki duvarlar muhtemelen kapali polyline degil. "
         "Cizimde duvar segmentleri eksiksiz olmalidir; yoksa AutoCAD'de "
         "EXPLODE / TRIM ile temizlenmeli. Alternatif olarak room_boundary "
         "katmanina manuel kapali polyline cizilebilir."],
        ["Eksik tip uyarisi", "tip_definitions.yaml'a yeni kodu ekle veya "
                              "config_gaps.synthesize ile sablon olustur."],
        ["Yanlis alan degeri",
         "DXF birimi unitless ($INSUNITS=0) olabilir.  AutoCAD'de "
         "INSUNITS komutuyla METRES (6) veya MILLIMETERS (4) ayarla."],
        ["Acikliklar mahale eslesmiyor",
         "Kapi/pencere blok insert noktasi mahal poligonunun disinda "
         "olabilir.  1 m'lik tolerans var; daha buyuk sapmalarda blok "
         "insert noktasini duvar uzerine kaydirin."],
        ["Bos sutunlar (NET DOSEME = 0)",
         "Mahale tip atanmamis demektir.  Ya tip_assigner kurali eklenmeli "
         "(mahal adi -> profile) ya da Excel'de manuel duzeltilmeli."],
    ]))
    story.append(PageBreak())

    # ====== 10. SSS ======
    story.append(Paragraph("10. Sik Sorulan Sorular (SSS)", s["h1"]))
    qa = [
        ("AutoCAD lisansim yok, kullanabilir miyim?",
         "Evet.  DXF dosyasi varsa hicbir AutoCAD bilesenine ihtiyac yoktur. "
         "DWG icin de yalnizca ucretsiz ODA File Converter gerekir."),
        ("ODA File Converter ucretsiz mi?",
         "Bireysel/firma kullanimi icin ucretsiz indirilebilir.  Ticari "
         "redistribution lisansi ayri.  Detay: opendesign.com"),
        ("Bakanlik birim fiyat guncellemesi nasil olacak?",
         "poz_library.yaml dosyasinda birim_fiyat alanini elle "
         "guncelleyebilirsiniz.  Ileride Faz 5+'ta 'birim fiyat import' "
         "modulu otomatize edecektir."),
        ("Excel'i acinca #REF! hatalari oluyor mu?",
         "Hayir.  Sistem tum hesaplari deger olarak yazar; sadece toplam "
         "satirlari SUM formulu kullanir.  Mevcut R22 dosyasindaki "
         "#REF! hatalari yeni cikti dosyasinda olmaz."),
        ("Iki revize cizim arasinda fark almak mumkun mu?",
         "Evet, RevisionComparator modulu var (mahal eklendi/silindi/buyudu, "
         "poz tutar farki).  CLI komutu olarak su an exposed degil ama "
         "pipeline'i iki kez calistirip programatik karsilastirilir."),
        ("Mekanik / elektrik / statik metraji yapar mi?",
         "Hayir, su an sadece mimari kapsam.  Yol haritasinda Faz 4'te "
         "mimari kabuk imalatlari da var.  Mekanik/elektrik buyuk bir "
         "ek kapsamdir; ileri faz olarak planlanabilir."),
        ("Mahallere otomatik tip atanmasini sevmedim, manuel mu yapacagim?",
         "Pipeline ilk atamayi yapar; UI'in 'Mahal Listesi' sekmesinde "
         "veya Excel'in MAHAL sayfasinda toplu degisiklik yapilip pipeline "
         "tekrar calistirilir.  Kalici cozum: tip_assigner.py icindeki "
         "kurallari firmanin standartiyla zenginlestirmek."),
        ("Cok katli proje destekleniyor mu?",
         "Her kati ayri DXF olarak verirseniz tek tek calistirip Excel'leri "
         "birlestirebilirsiniz.  Tek DXF'te coklu kat bilgisi DWG'nin "
         "model space yapisina baglidir; mahal koduna 'B / Z / 1 / cati' "
         "gibi kat prefix'i konursa otomatik gruplanir."),
    ]
    for q, a in qa:
        story.append(Paragraph(f"<b>S:</b> {q}", s["h3"]))
        story.append(Paragraph(f"<b>C:</b> {a}", s["body"]))

    # ====== KAPANIS ======
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(
        "Klavuzun sonu - sorular icin teknik ekibe veya proje yoneticisine "
        "danisiniz.",
        s["caption"]))

    doc.build(story, onFirstPage=_page_chrome, onLaterPages=_page_chrome)
    return out_path


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    target = Path(argv[0]) if argv else Path("docs/Metraj_Kullanim_Klavuzu.pdf")
    out = build(target)
    print(f"Kullanim klavuzu olusturuldu: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
