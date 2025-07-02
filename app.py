import streamlit as st
import pandas as pd
import google.generativeai as genai
import os
import requests
from bs4 import BeautifulSoup
from newspaper import Article
import io

# --- Pindahkan st.set_page_config() ke sini, paling atas ---
st.set_page_config(page_title="Senticon by Burson", layout="wide", initial_sidebar_state="collapsed")

# --- Konfigurasi Gemini API ---
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except KeyError:
    st.error("Google API Key tidak ditemukan. Pastikan Anda telah menempatkannya di .streamlit/secrets.toml.")
    st.stop()

# --- Fungsi-fungsi Backend (tidak berubah) ---
@st.cache_data
def load_prompt_template(file_path="prompt_template.txt"):
    try:
        with open(file_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        st.error(f"File prompt_template.txt tidak ditemukan.")
        st.stop()

PROMPT_TEMPLATE = load_prompt_template()

@st.cache_data(show_spinner=False)
def get_sentiment_from_gemini(text, context, model_name="gemini-1.5-flash-latest"):
    if not text or not context:
        return "N/A", "N/A"
    prompt = PROMPT_TEMPLATE.replace("{TEKS_INPUT}", text).replace("{KONTEKS_INPUT}", context)
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt,
                                          generation_config=genai.types.GenerationConfig(
                                              temperature=0.2,
                                              max_output_tokens=150
                                          ))
        response_text = response.text.strip()
        sentiment, reason = "Not Found", "Not Found"
        for line in response_text.split('\n'):
            if line.lower().startswith("sentimen:"):
                sentiment = line.split(':', 1)[1].strip()
            elif line.lower().startswith("alasan:"):
                reason = line.split(':', 1)[1].strip()
        return sentiment, reason
    except Exception as e:
        return f"API Error", str(e)

@st.cache_data
def get_text_from_url(url, fallback_title):
    if not url or not isinstance(url, str) or not url.startswith('http'):
        return fallback_title, "Judul dari File (URL tidak valid)"
    try:
        article = Article(url)
        article.download()
        article.parse()
        if article.text and len(article.text.split()) > 20:
            return article.text, "Newspaper3k"
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            paragraphs = soup.find_all('p')
            full_text = "\n".join([p.get_text() for p in paragraphs if p.get_text().strip()])
            if full_text and len(full_text.split()) > 20:
                return full_text, "BeautifulSoup"
        except Exception:
            pass
        if fallback_title:
            return fallback_title, "Judul dari File"
        return "", "Gagal Total"
    except Exception:
        return fallback_title, "Judul dari File (URL Gagal Diakses)"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='AnalisisSentimen')
    return output.getvalue()

# --- Streamlit UI dengan Tampilan Baru ---
st.title("🤖 Analisis Sentimen Berbasis Konteks")
st.markdown("Analisis sentimen berita dari URL atau teks yang ada dengan kategori yang lebih detail.")

input_method = st.radio("Pilih metode input:", ("Unggah File", "Input URL Manual"), horizontal=True)

if input_method == "Unggah File":
    st.header("📤 Unggah & Konfigurasi File")
    uploaded_file = st.file_uploader("Pilih file Excel (.xlsx) atau CSV (.csv)", type=["xlsx", "csv"])

    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
            st.success("File berhasil diunggah!")
            
            with st.expander("Lihat 5 baris pertama dari data Anda"):
                st.dataframe(df.head())

            st.subheader("⚙️ Konfigurasi Analisis")
            col1, col2 = st.columns(2)
            
            with col1:
                analysis_source = st.radio(
                    "Pilih sumber teks untuk dianalisis:",
                    ("Tarik berita dari kolom URL", "Analisis teks yang sudah ada dari kolom Teks/Snippet"),
                    key="analysis_source"
                )
            
            with col2:
                target_context = st.text_input("Masukkan Konteks Analisis", placeholder="misal: harga, layanan, pemerintah")

            col_options = df.columns.tolist()
            if analysis_source == "Tarik berita dari kolom URL":
                c1, c2 = st.columns(2)
                with c1:
                    url_column = st.selectbox("Pilih kolom URL berita:", col_options, index=0)
                with c2:
                    title_column = st.selectbox("Pilih kolom Snippet/judul bila gagal tarik berita  (fallback):", col_options, index=1 if len(col_options)>1 else 0)
                snippet_column = None
            else:
                snippet_column = st.selectbox("Pilih kolom Teks/Snippet:", col_options)
                url_column, title_column = None, None

            if st.button("🚀 Mulai Analisis", use_container_width=True, type="primary"):
                if target_context and ((url_column and title_column) or snippet_column):
                    st.info(f"Memulai analisis untuk konteks '{target_context}'...")
                    
                    df['Teks_Dianalisis'], df['Sumber_Teks'], df['Sentimen'], df['Alasan_Sentimen'] = [""] * 4
                    progress_bar = st.progress(0, text="Memproses...")
                    
                    for i, row in df.iterrows():
                        text_content, source = "", ""
                        if analysis_source == "Tarik berita dari kolom URL":
                            text_content, source = get_text_from_url(str(row[url_column]), str(row[title_column]))
                        else:
                            text_content, source = str(row[snippet_column]), "Teks dari File"
                        
                        df.at[i, 'Teks_Dianalisis'], df.at[i, 'Sumber_Teks'] = text_content, source
                        
                        if text_content:
                            sentiment, reason = get_sentiment_from_gemini(text_content, target_context)
                            df.at[i, 'Sentimen'], df.at[i, 'Alasan_Sentimen'] = sentiment, reason
                        else:
                            df.at[i, 'Sentimen'], df.at[i, 'Alasan_Sentimen'] = "Teks Tidak Ditemukan", "Tidak ada teks yang bisa dianalisis."
                        
                        progress_bar.progress((i + 1) / len(df), text=f"Memproses baris {i+1}/{len(df)}")

                    st.success("Analisis sentimen selesai!")
                    
                    st.header("📊 Hasil Analisis")
                    st.dataframe(df)
                    
                    excel_data = to_excel(df)
                    st.download_button(
                        label="📥 Unduh Hasil sebagai Excel (.xlsx)",
                        data=excel_data,
                        file_name=f"analisis_sentimen_{target_context}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                else:
                    st.warning("Harap lengkapi semua pilihan konfigurasi di atas.")
        except Exception as e:
            st.error(f"Terjadi kesalahan saat memproses file: {e}")

elif input_method == "Input URL Manual":
    st.header("📄 Analisis URL Tunggal")
    manual_url = st.text_input("Masukkan URL berita yang ingin dianalisis:")
    target_context_manual = st.text_input("Masukkan Konteks Analisis", placeholder="misal: harga, layanan, baterai")

    if st.button("🚀 Analisis URL Ini", use_container_width=True, type="primary"):
        if manual_url and target_context_manual:
            with st.spinner(f"Menganalisis sentimen untuk konteks '{target_context_manual}'..."):
                text_content, source = get_text_from_url(manual_url, f"Judul dari {manual_url}")
                
                if text_content:
                    sentiment, reason = get_sentiment_from_gemini(text_content, target_context_manual)
                    
                    st.subheader("Hasil Analisis")
                    st.metric(label=f"Sentimen terhadap '{target_context_manual}'", value=sentiment)
                    st.info(f"**Alasan:** {reason}")
                    
                    with st.expander("Lihat teks yang dianalisis"):
                        st.write(f"*(Sumber Teks: {source})*")
                        st.write(text_content)
                else:
                    st.error("Gagal mengambil teks dari URL. URL mungkin tidak valid atau situs tidak dapat diakses.")
        else:
            st.warning("Harap masukkan URL dan Konteks target.")

st.markdown("---")
st.markdown("Dibuat dengan Google Gemini API")
