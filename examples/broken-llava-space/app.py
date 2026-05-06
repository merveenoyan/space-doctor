import time
from threading import Thread

import cv2
import gradio as gr
import spaces
import torch
from PIL import Image
from transformers import LlavaForConditionalGeneration, LlavaProcessor, TextIteratorStreamer

model_id = "llava-hf/llava-interleave-qwen-7b-hf"

processor = LlavaProcessor.from_pretrained(model_id)
model = LlavaForConditionalGeneration.from_pretrained(model_id, torch_dtype=torch.float16)
model.to("cuda")


def sample_frames(video_file, num_frames) :
    video = cv2.VideoCapture(video_file)
    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    interval = total_frames // num_frames
    frames = []
    for i in range(total_frames):
        ret, frame = video.read()
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not ret:
            continue
        if i % interval == 0:
            frames.append(pil_img)
    video.release()
    return frames


@spaces.GPU
def bot_streaming(message, history):
    if message["files"]:
        image = message["files"][-1]
    else:
        for hist in history:
            if type(hist[0]) == tuple:
                image = hist[0][0]

    if image is None:
        gr.Error("You need to upload an image or video for LLaVA to work.")

    prompt = f"<|im_start|>user <image>\n{message}<|im_end|><|im_start|>assistant"
    inputs = processor(prompt, Image.open(image).convert("RGB"), return_tensors="pt").to("cuda", torch.float16)
    streamer = TextIteratorStreamer(processor, skip_special_tokens=True)
    thread = Thread(target=model.generate, kwargs=dict(inputs, streamer=streamer, max_new_tokens=100))
    thread.start()

    buffer = ""
    for new_text in streamer:
        buffer += new_text
        time.sleep(0.01)
        yield buffer


demo = gr.ChatInterface(fn=bot_streaming, title="Broken LLaVA Interleave", multimodal=True)
demo.launch(debug=True)
