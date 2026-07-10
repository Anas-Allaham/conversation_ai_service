# This will:
# load Whisper
# transcribe audio


import os
import sys

# جلب المسار الفيزيائي للمجلد الذي يحتوي على ملفات الـ DLL داخل الـ venv
venv_nvidia_path = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cublas", "bin")

# إضافة المسار مباشرة لمتغير البيئة PATH الخاص بنظام تشغيل الويندوز ليقرأه كود الـ C++ فوراً
if os.path.exists(venv_nvidia_path):
    os.environ["PATH"] = venv_nvidia_path + os.pathsep + os.environ["PATH"]

# الآن نقوم باستدعاء المكتبة بأمان تام
from faster_whisper import WhisperModel

# إضافة مسار الـ cudnn أيضاً إلى الـ PATH لضمان استقرار التشغيل بالكامل
venv_cudnn_path = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cudnn", "bin")
if os.path.exists(venv_cudnn_path):
    os.environ["PATH"] = venv_cudnn_path + os.pathsep + os.environ["PATH"]


# Load model once globally on GPU
# نقوم بتغيير device إلى cuda، ونغير compute_type إلى float16 وهي الصيغة المثالية والأسرع لكروت شاشة NVIDIA الحديثة
model = WhisperModel(
    "base",
    device="cuda",
    compute_type="float16"  # كروت ROG STRIX تدعم float16 بكفاءة خارقة وتوفر سرعة هائلة
)

def transcribe_audio(audio_path):
    """
    Transcribes audio file into text.
    """

    print("Transcribing audio on GPU...")

    segments, info = model.transcribe(
        audio_path,
        language="en",
        vad_filter=True,
        initial_prompt="""
    English learning conversation.
    Common words:
    conversation,
    skills,
    grammar,
    vocabulary,
    pronunciation,
    speaking,
    listening
    """
    )
    transcription = ""

    for segment in segments:
        transcription += segment.text + " "

    transcription = transcription.strip()

    print(f"Transcription: {transcription}")

    return transcription