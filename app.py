import os
import uuid
import shutil
import zipfile
import sys
import wave
import numpy as np
import matplotlib.pyplot as plt
import traceback
import threading
import subprocess
import hashlib
import json

os.environ["TORCHAUDIO_USE_TORCHCODEC"] = "0"

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


# -------------------------------------------------------------------
# Инициализация приложения и настройки
# -------------------------------------------------------------------

app = FastAPI(title="Audio Separator API", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

PROCESSING_TIMEOUT = 600
MAX_SIZE_MB = 200

ALLOWED_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
}

# -------------------------------------------------------------------
# Вспомогательные функции
# -------------------------------------------------------------------

# Вычисление хеша файла
def get_file_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

# Проверка типа файла
def validate_file_content_type(content_type: str) -> bool:
    return content_type in ALLOWED_TYPES

# Проверка размера файла
def validate_file_size(content: bytes) -> bool:
    return len(content) / (1024 * 1024) <= MAX_SIZE_MB

# -------------------------------------------------------------------
# Запуск Demucs с ограничением по времени
# -------------------------------------------------------------------

def run_demucs_with_timeout(input_path: str, job_id: str):
    output_path = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(output_path, exist_ok=True)

    python_path = sys.executable

    cmd = [
        python_path,
        "-m",
        "demucs",
        "-n",
        "htdemucs",
        "--out",
        output_path,
        input_path
    ]

    print(f"Running command: {' '.join(cmd)}")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    def kill_process():
        print(f"Timeout {PROCESSING_TIMEOUT}s reached, killing process")
        process.kill()

    timer = threading.Timer(PROCESSING_TIMEOUT, kill_process)
    timer.start()

    try:
        stdout, stderr = process.communicate()
        timer.cancel()

        print(f"Demucs return code: {process.returncode}")
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            print(f"Demucs error: {error_msg}")
            raise RuntimeError(f"Demucs failed: {error_msg}")

        return output_path

    except Exception as e:
        timer.cancel()
        print(f"Exception in Demucs: {e}")
        raise
    finally:
        if process.poll() is None:
            process.kill()

# -------------------------------------------------------------------
# Поиск файлов стемов
# -------------------------------------------------------------------

def find_stems(job_id: str):
    job_path = os.path.join(OUTPUT_DIR, job_id)

    if not os.path.exists(job_path):
        print(f"Job path does not exist: {job_path}")
        return None

    stems = {}
    
    # Demucs создает структуру: output_path/htdemucs/имя_файла/
    for root, _, files in os.walk(job_path):
        for f in files:
            if f.endswith(".wav"):
                full_path = os.path.join(root, f)
                name = f.lower()
                print(f"Found file: {name}")

                if "vocals" in name:
                    stems["vocals"] = full_path
                elif "drums" in name:
                    stems["drums"] = full_path
                elif "bass" in name:
                    stems["bass"] = full_path
                elif "other" in name:
                    stems["other"] = full_path
    
    print(f"Found stems: {list(stems.keys())}")
    return stems if stems else None

# -------------------------------------------------------------------
# Создание спектрограмм
# -------------------------------------------------------------------

# Сохранение спектрограммы из WAV-файла
def save_spectrogram(wav_path: str, out_path: str):
    try:
        with wave.open(wav_path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            signal = np.frombuffer(frames, dtype=np.int16).astype(np.float32)

            if wf.getnchannels() == 2:
                signal = signal[::2]

            if np.max(np.abs(signal)) != 0:
                signal = signal / np.max(np.abs(signal))

            plt.figure(figsize=(6, 4))
            plt.specgram(signal, Fs=wf.getframerate())
            plt.tight_layout()
            plt.savefig(out_path)
            plt.close()
    except Exception as e:
        print(f"Error creating spectrogram: {e}")

# Получение пути к спектрограмме (создание при отсутствии)
def get_spectrogram_path(job_id: str, stem: str):
    spec_dir = os.path.join(OUTPUT_DIR, job_id, "spectrograms")
    os.makedirs(spec_dir, exist_ok=True)

    path = os.path.join(spec_dir, f"{stem}.png")

    if not os.path.exists(path):
        stems = find_stems(job_id)
        if not stems or stem not in stems:
            return None
        save_spectrogram(stems[stem], path)

    return path

# -------------------------------------------------------------------
# Упаковка стемов в ZIP и получение базового URL
# -------------------------------------------------------------------

# Создание ZIP-архива со стемами
def create_zip(stems: dict, job_id: str):
    zip_path = os.path.join(OUTPUT_DIR, job_id, f"{job_id}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in stems.items():
            z.write(v, f"{k}.wav")

    return zip_path

# Формирование базового URL из запроса
def get_base_url(request: Request):
    return f"{request.url.scheme}://{request.url.netloc}"

# -------------------------------------------------------------------
# HTML
# -------------------------------------------------------------------

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Audio Separator - Разделение музыки на инструментальные дорожки</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
        }
        input[type="file"] {
            margin: 20px 0;
            padding: 10px;
        }
        button {
            background: #007bff;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
        }
        button:hover {
            background: #0056b3;
        }
        .result {
            margin-top: 30px;
            padding: 20px;
            background: #f9f9f9;
            border-radius: 5px;
        }
        .stem {
            margin: 20px 0;
            padding: 15px;
            background: white;
            border-radius: 5px;
            border: 1px solid #ddd;
        }
        audio {
            width: 100%;
            margin: 10px 0;
        }
        .loading {
            color: #007bff;
            font-style: italic;
        }
        .error {
            color: red;
        }
        a {
            color: #007bff;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎵 Audio Separator</h1>
        <p>Загрузите аудиофайл (WAV или MP3, до 200 МБ)</p>
        
        <input type="file" id="fileInput" accept="audio/*">
        <button onclick="upload()">Разделить на дорожки</button>
        
        <div id="result"></div>
    </div>

    <script>
        async function upload() {
            const file = document.getElementById('fileInput').files[0];
            if (!file) {
                alert('Выберите файл');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            const resultDiv = document.getElementById('result');
            resultDiv.innerHTML = '<div class="loading">⏳ Обработка файла... Это может занять несколько минут...</div>';

            try {
                const res = await fetch('/separate?mode=json', { 
                    method: 'POST', 
                    body: formData 
                });
                
                if (!res.ok) {
                    const error = await res.text();
                    throw new Error(error);
                }
                
                const data = await res.json();
                
                let html = '<div class="result"><h3>✅ Результат разделения:</h3>';
                html += `<p><a href="${data.zip_url}" download>📦 Скачать все дорожки (ZIP)</a></p>`;
                
                const stems = ['vocals', 'drums', 'bass', 'other'];
                const stemNames = {'vocals': '🎤 Вокал', 'drums': '🥁 Ударные', 'bass': '🎸 Бас', 'other': '🎹 Остальное'};
                
                for (const stem of stems) {
                    if (data.spectrograms[stem]) {
                        const audioUrl = data.spectrograms[stem].replace('/spectrogram', '/audio');
                        html += `
                            <div class="stem">
                                <strong>${stemNames[stem]}</strong><br>
                                <audio controls src="${audioUrl}"></audio><br>
                                <a href="${data.spectrograms[stem]}" target="_blank">📊 Спектрограмма</a>
                            </div>
                        `;
                    }
                }
                
                html += '</div>';
                resultDiv.innerHTML = html;
                
            } catch (error) {
                resultDiv.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
            }
        }
    </script>
</body>
</html>
"""

# -------------------------------------------------------------------
# Основные эндпоинты API
# -------------------------------------------------------------------

# Главная страница с веб-интерфейсом
@app.get("/", response_class=HTMLResponse)
async def web_interface():
    return HTMLResponse(content=HTML_PAGE)

# Проверка работоспособности сервиса
@app.get("/health")
def health():
    return {"status": "ok"}

# Разделение аудиофайла на стемы
@app.post("/separate")
async def separate(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Query("json")
):
    if not file.filename:
        raise HTTPException(400, "No file")

    if not validate_file_content_type(file.content_type):
        raise HTTPException(400, f"Unsupported format. Use WAV or MP3. Got: {file.content_type}")

    content = await file.read()

    if not validate_file_size(content):
        raise HTTPException(400, f"File too large. Max {MAX_SIZE_MB} MB")

    temp_path = os.path.join(UPLOAD_DIR, f"temp_{uuid.uuid4()}_{file.filename}")

    with open(temp_path, "wb") as f:
        f.write(content)

    file_hash = get_file_hash(temp_path)
    cache_file = os.path.join(CACHE_DIR, f"{file_hash}.json")

    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            cached_result = json.load(f)
        os.remove(temp_path)
        return cached_result

    job_id = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")

    shutil.move(temp_path, input_path)

    try:
        print(f"Starting separation for job {job_id}, file: {input_path}")
        run_demucs_with_timeout(input_path, job_id)

        stems = find_stems(job_id)
        if not stems:
            raise HTTPException(500, "No stems generated")

        create_zip(stems, job_id)

        base_url = get_base_url(request)

        result = {
            "job_id": job_id,
            "zip_url": f"{base_url}/download_zip/{job_id}",
            "spectrograms": {
                k: f"{base_url}/spectrogram/{job_id}/{k}"
                for k in stems.keys()
            }
        }

        with open(cache_file, "w") as f:
            json.dump(result, f)

        print(f"Separation completed for job {job_id}")
        return result

    except Exception as e:
        print("=" * 50)
        print("ERROR:")
        traceback.print_exc()
        print("=" * 50)
        raise HTTPException(500, str(e))

# -------------------------------------------------------------------
# Эндпоинты для скачивания файлов
# -------------------------------------------------------------------

# Выдача аудиофайла стема для прослушивания
@app.get("/audio/{job_id}/{stem}")
def audio_stem(job_id: str, stem: str):
    stems = find_stems(job_id)
    if not stems or stem not in stems:
        raise HTTPException(404, f"Stem '{stem}' not found")
    
    return FileResponse(
        stems[stem], 
        media_type="audio/wav",
        filename=f"{stem}.wav"
    )

# Скачивание ZIP-архива со всеми стемами
@app.get("/download_zip/{job_id}")
def download_zip(job_id: str):
    zip_path = os.path.join(OUTPUT_DIR, job_id, f"{job_id}.zip")

    if not os.path.exists(zip_path):
        raise HTTPException(404, "ZIP archive not found")

    return FileResponse(
        zip_path, 
        media_type="application/zip",
        filename=f"stems_{job_id}.zip"
    )

# Выдача спектрограммы стема
@app.get("/spectrogram/{job_id}/{stem}")
def spectrogram(job_id: str, stem: str):
    path = get_spectrogram_path(job_id, stem)

    if not path:
        raise HTTPException(404, f"Spectrogram for '{stem}' not found")

    return FileResponse(path, media_type="image/png")

# -------------------------------------------------------------------
# Точка входа при запуске скрипта
# -------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)