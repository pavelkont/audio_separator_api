# Audio Separator API

Сервис для разделения музыки на инструментальные дорожки (вокал, барабаны, бас, остальное) с использованием Demucs.

## Возможности

- Разделение аудио на 4 стема: vocals, drums, bass, other
- Поддержка WAV и MP3 (до 200 МБ)
- REST API на FastAPI
- Веб-интерфейс для загрузки и прослушивания
- Спектрограммы стемов
- Кэширование результатов по хешу файла
- Ограничение времени обработки (600 сек)
- Docker контейнеризация

## Быстрый старт

### Локальный запуск

```bash
pip install -r requirements.txt
python app.py
```
Откройте в браузере: http://localhost:8000

### Запуск в Docker

```bash
docker-compose up --build
```
Откройте в браузере: http://localhost:8001

## API Endpoints

- GET `/` — веб-интерфейс
- GET `/health` — проверка статуса
- POST `/separate` — загрузить файл, получить стемы
- GET `/audio/{job_id}/{stem}` — прослушать стем
- GET `/download_zip/{job_id}` — скачать ZIP
- GET `/spectrogram/{job_id}/{stem}` — получить спектрограмму

### Пример запроса (curl)

```bash
curl -X POST http://localhost:8000/separate \
  -F "file=@/path/to/your/song.mp3"
```

### Пример ответа

```json
{
  "job_id": "abc-123",
  "zip_url": "http://localhost:8000/download_zip/abc-123",
  "spectrograms": {
    "vocals": "http://localhost:8000/spectrogram/abc-123/vocals",
    "drums": "http://localhost:8000/spectrogram/abc-123/drums",
    "bass": "http://localhost:8000/spectrogram/abc-123/bass",
    "other": "http://localhost:8000/spectrogram/abc-123/other"
  }
}
```

## Оценка качества

Метрики рассчитаны на датасете MUSDB18 (5 треков по 30 секунд).

| Стем | SDR (дБ) | SIR (дБ) | SAR (дБ) |
|------|----------|----------|----------|
| Vocals | -4.86 | 21.59 | -4.80 |
| Drums | -8.75 | 13.79 | -6.60 |
| Bass | -12.79 | 6.54 | -7.39 |
| Other | -5.54 | 15.42 | -5.34 |
SDR — качество разделения (выше лучше).
SIR — подавление других инструментов (выше лучше).
SAR — уровень артефактов (выше лучше).

## Структура проекта

```text
.
├── app.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── audio_separator.ipynb
├── report.docx
├── uploads/
├── outputs/
├── cache/
└── README.md
```

## Зависимости

Python 3.11+
FastAPI
Demucs 4.0+
PyTorch
NumPy, Matplotlib
Полный список в requirements.txt.

## Системные требования

ОЗУ: от 4 ГБ (рекомендуется 8 ГБ+)
Процессор: любой современный (GPU опционально, ускоряет обработку)
Диск: от 2 ГБ свободного места + место для загружаемых файлов

## Лицензия

Для некоммерческого использования.

## Автор

Telegram: @pavel_kont
