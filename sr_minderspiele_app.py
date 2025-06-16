import streamlit as st
import pandas as pd
from datetime import date
import io
import zipfile

st.set_page_config(page_title="SR-Minderspiele Auswertung", layout="wide")

st.title("Auswertung SR-Minderspiele für mehrere Spielzeiten")

st.markdown("""
Diese App berechnet:
- **Minderspiele** je Verein pro Spielzeit
- **Fehlabgabe** gemäß §38 Abs. 3 SpO
- **Punktabzug** bei drei aufeinanderfolgenden Jahren mit über 30% Minderspielen
- Erstellung der Importdateien für nuLiga mit korrekter Kodierung für Umlaute und Sonderzeichen
- Export aller Importdateien als ZIP
- Export der Gesamtauswertung als Excel-Datei
- Export der Punktabzugstabelle als Excel-Datei
""")

uploaded_soll_2022 = st.file_uploader("📥 Datei mit Soll/Ist-Zahlen 2022/23", type=["csv", "xlsx"])
uploaded_sr_2022 = st.file_uploader("📥 Datei mit SR-Einsätzen 2022/23", type=["csv", "xlsx"])

uploaded_soll_2023 = st.file_uploader("📥 Datei mit Soll/Ist-Zahlen 2023/24", type=["csv", "xlsx"])
uploaded_sr_2023 = st.file_uploader("📥 Datei mit SR-Einsätzen 2023/24", type=["csv", "xlsx"])

uploaded_soll_2024 = st.file_uploader("📥 Datei mit Soll/Ist-Zahlen 2024/25", type=["csv", "xlsx"])
uploaded_sr_2024 = st.file_uploader("📥 Datei mit SR-Einsätzen 2024/25", type=["csv", "xlsx"])

def to_float(x):
    try:
        return float(str(x).replace(',', '.'))
    except:
        return 0.0

def lade_csv_oder_excel(uploaded_file):
    if uploaded_file:
        if uploaded_file.name.endswith(".csv"):
            return pd.read_csv(uploaded_file, sep=';', encoding='ISO-8859-1')
        elif uploaded_file.name.endswith(".xlsx"):
            return pd.read_excel(uploaded_file)
    return None

def verarbeite_jahr(soll_df, sr_df, saison):
    soll_df = soll_df.copy()
    soll_df['Soll'] = soll_df['Soll-Anzahl'].apply(to_float)
    soll_df['Ist'] = soll_df['Ist-Anzahl'].apply(to_float)
    soll_df['Minder'] = (soll_df['Soll'] - soll_df['Ist']).apply(lambda x: max(0, x))
    soll_df['Quote'] = soll_df.apply(lambda row: row['Minder'] / row['Soll'] if row['Soll'] > 0 else 0.0, axis=1)

    bonus_df = sr_df.copy()
    bonus_df['Anzahl geleitet'] = bonus_df['Anzahl geleitet'].fillna(0)
    bonus_df['Bonus'] = bonus_df['Anzahl geleitet'].apply(lambda x: 1 if x >= 15 else 0)
    bonus_verein = bonus_df.groupby('VereinsNr')['Bonus'].sum().reset_index()
    bonus_verein.columns = ['VereinsNr', 'Bonus_SR']

    soll_df['Vereins-Nr'] = soll_df['Vereins-Nr'].astype(str).str.strip()
    bonus_verein['VereinsNr'] = bonus_verein['VereinsNr'].astype(str).str.strip()

    soll_df = soll_df.merge(bonus_verein, how='left', left_on='Vereins-Nr', right_on='VereinsNr')
    soll_df['Bonus_SR'] = soll_df['Bonus_SR'].fillna(0)
    soll_df['Saison'] = saison

    return soll_df[['Vereins-Nr', 'Vereinsname', 'Vereins-Region', 'Soll', 'Ist', 'Minder', 'Quote', 'Bonus_SR', 'Saison']]

def berechne_beitrag_regel(minder, bonus):
    m22, m23, m24 = minder
    b22, b23, b24 = bonus
    beitrag = [0.0, 0.0, 0.0]

    if m22 > 0:
        beitrag[0] = m22 * 15 - b22 * 50

    if m23 > 0:
        if m22 <= 0:
            beitrag[1] = m23 * 15 - b23 * 50
        elif m22 > 0:
            if m22 <= m23:
                beitrag[1] = m22 * 25 + (m23 - m22) * 15 - b23 * 50
            else:
                beitrag[1] = m23 * 25 - b23 * 50

    if m24 > 0:
        if m23 <= 0:
            beitrag[2] = m24 * 15 - b24 * 50

        elif m23 > 0 and m22 <= 0:
            if m24 > m23:
                beitrag[2] = m23 * 25 + (m24 - m23) * 15 - b24 * 50
            else:
                beitrag[2] = m24 * 25 - b24 * 50

        elif m23 > 0 and m22 > 0:
            if m22 < m23 and m23 > m24:
                # Fall: steigende Staffelung, dann Rückgang
                beitrag[2] = (
                    m22 * 50 +
                    (m24 - m22) * 25 -
                    b24 * 50
                )
            elif m24 > m23:
                if m22 < m23:
                    beitrag[2] = (
                        m22 * 50 +
                        (m23 - m22) * 25 +
                        (m24 - m23) * 15 -
                        b24 * 50
                    )
                else:
                    beitrag[2] = m23 * 50 + (m24 - m23) * 15 - b24 * 50

            elif m24 == m23:
                if m22 < m23:
                    beitrag[2] = m22 * 50 + (m23 - m22) * 25 - b24 * 50
                else:
                    beitrag[2] = m24 * 50 - b24 * 50

            elif m24 < m23:
                if m22 == m23:
                    beitrag[2] = m24 * 50 - b24 * 50
                elif m22 > m23:
                    beitrag[2] = m24 * 50 - b24 * 50

    beitrag = [max(0.0, round(b, 2)) for b in beitrag]
    return beitrag

def berechne_punktabzug(gesamt_df):
    gruppiert = gesamt_df.pivot_table(index='Vereins-Nr', columns='Saison', values='Quote')
    abzug_df = pd.DataFrame(index=gruppiert.index)
    abzug_df['Quote_22_23'] = gruppiert.get('2022/23', 0)
    abzug_df['Quote_23_24'] = gruppiert.get('2023/24', 0)
    abzug_df['Quote_24_25'] = gruppiert.get('2024/25', 0)

    def berechne_reihe(row):
        folgen = [row['Quote_22_23'] > 0.3, row['Quote_23_24'] > 0.3, row['Quote_24_25'] > 0.3]
        if sum(folgen) == 3:
            return 2 + 2 * (sum(folgen) - 3)
        return 0

    abzug_df['Punktabzug'] = abzug_df.apply(berechne_reihe, axis=1)
    abzug_df = abzug_df.reset_index()
    vereinsinfo = gesamt_df.drop_duplicates(subset='Vereins-Nr')[['Vereins-Nr', 'Vereinsname', 'Vereins-Region']]
    abzug_df = abzug_df.merge(vereinsinfo, on='Vereins-Nr', how='left')
    return abzug_df[['Vereins-Nr', 'Vereinsname', 'Vereins-Region', 'Quote_22_23', 'Quote_23_24', 'Quote_24_25', 'Punktabzug']]

def erstelle_zip_export(df):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        today = date.today().strftime("%d.%m.%Y")
        for saison in df['Saison'].unique():
            saison_df = df[df['Saison'] == saison]
            for region in saison_df['Vereins-Region'].unique():
                region_df = saison_df[(saison_df['Vereins-Region'] == region) & (saison_df['Beitrag'] > 0)]
                if not region_df.empty:
                    export_df = pd.DataFrame({
                        'VereinNr': region_df['Vereins-Nr'],
                        'Lieferscheintext': f"Fehlabgabe gemäß §38 Abs. 3 SpO für SR-Minderspiele Saison {saison}",
                        'Datum': today,
                        'Betrag': region_df['Beitrag'].map(lambda x: f"{x:.2f}".replace('.', ','))
                    })
                    csv_bytes = export_df.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
                    filename = f"SR_Minderspiele_{saison.replace('/', '_')}_Bezirk_{region}.csv"
                    zip_file.writestr(filename, csv_bytes)
    return zip_buffer.getvalue()

if uploaded_soll_2022 and uploaded_sr_2022 and uploaded_soll_2023 and uploaded_sr_2023 and uploaded_soll_2024 and uploaded_sr_2024:
    df_22 = verarbeite_jahr(lade_csv_oder_excel(uploaded_soll_2022), lade_csv_oder_excel(uploaded_sr_2022), saison="2022/23")
    df_23 = verarbeite_jahr(lade_csv_oder_excel(uploaded_soll_2023), lade_csv_oder_excel(uploaded_sr_2023), saison="2023/24")
    df_24 = verarbeite_jahr(lade_csv_oder_excel(uploaded_soll_2024), lade_csv_oder_excel(uploaded_sr_2024), saison="2024/25")

    gesamt_df = pd.concat([df_22, df_23, df_24], ignore_index=True)
    gesamt_df = gesamt_df.sort_values(by=["Vereins-Nr", "Saison"])

    saison_index = {"2022/23": 0, "2023/24": 1, "2024/25": 2}
    vereinsgruppen = gesamt_df.groupby("Vereins-Nr")

    beitragswerte = []

    for vnr, gruppe in vereinsgruppen:
        gruppe = gruppe.sort_values(by="Saison")
        minderzahlen = [0.0, 0.0, 0.0]
        sr_bonus = [0, 0, 0]

        for _, row in gruppe.iterrows():
            idx = saison_index[row["Saison"]]
            minderzahlen[idx] = row["Minder"]
            sr_bonus[idx] = row["Bonus_SR"]

        beitrag_pro_jahr = berechne_beitrag_regel(minderzahlen, sr_bonus)

        for i, row in gruppe.iterrows():
            beitragswerte.append(beitrag_pro_jahr[saison_index[row["Saison"]]])

    gesamt_df["Beitrag"] = beitragswerte

    st.markdown("## 📊 Gesamtübersicht aller Vereine")
    st.dataframe(gesamt_df)

    zip_data = erstelle_zip_export(gesamt_df)
    st.download_button("📦 Gesamte CSV-Ausgabe als ZIP herunterladen", data=zip_data, file_name="SR_Minderspiele_Export.zip", mime="application/zip")

    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
        gesamt_df.to_excel(writer, index=False, sheet_name="Gesamtauswertung")
        abzug_df = berechne_punktabzug(gesamt_df)
        abzug_df.to_excel(writer, index=False, sheet_name="Punktabzug")
    st.download_button("📊 Gesamtauswertung als Excel-Datei", data=excel_buffer.getvalue(), file_name="SR_Minderspiele_Gesamtauswertung.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("## ⚖️ Punktabzug gemäß §17 SRO und SPO")
    abzug_df = berechne_punktabzug(gesamt_df)
    st.dataframe(abzug_df[abzug_df['Punktabzug'] > 0])

    st.markdown("### 📉 Visualisierung: Punktabzüge pro Verein")
    abzug_anzuzeigen = abzug_df[abzug_df['Punktabzug'] > 0].sort_values(by="Punktabzug", ascending=False)
    if not abzug_anzuzeigen.empty:
        st.bar_chart(data=abzug_anzuzeigen.set_index("Vereinsname")["Punktabzug"])

    st.markdown("### 📈 Trendanalyse: Entwicklung der Minderspiele")
    trend_df = gesamt_df.groupby(['Saison'])[['Soll', 'Ist', 'Minder']].sum().reset_index()
    st.line_chart(trend_df.set_index('Saison'))

    st.markdown("### 📍 Trendanalyse pro Bezirk")
    trend_bezirk = gesamt_df.groupby(['Saison', 'Vereins-Region'])[['Soll', 'Ist', 'Minder']].sum().reset_index()
    for bezirk in trend_bezirk['Vereins-Region'].unique():
        st.markdown(f"#### Bezirk: {bezirk}")
        df_b = trend_bezirk[trend_bezirk['Vereins-Region'] == bezirk].sort_values(by='Saison')
        st.line_chart(df_b.set_index('Saison')[['Soll', 'Ist', 'Minder']])
