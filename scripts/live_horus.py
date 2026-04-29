#!/usr/bin/env python3

import asyncio
import os
import json
import numpy as np
import sounddevice as sd
import faiss
import queue
import threading
import traceback
import inspect
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# 🤖 ROS 2 Integration
try:
    import rclpy
    from std_msgs.msg import String

    ROS_ENABLED = True
except ImportError:
    ROS_ENABLED = False
    logger.warning("rclpy (ROS 2) not detected. Running in simulation mode.")

from google import genai
from google.genai import types
from vertexai.language_models import TextEmbeddingModel
import vertexai

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
PROJECT_ID = "project-ee6fbfda-83e5-4eed-bf2"
LOCATION = "us-central1"
GOOGLE_CRED_PATH = r"/home/abdelrahman/project/src/articubot_one/scripts/project-ee6fbfda-83e5-4eed-bf2-80b20b31cbba.json"
KB_PATH = r"/home/abdelrahman/project/src/articubot_one/scripts/TourGuideRag.txt"
GEMINI_API_KEY = "REDACTED"  # Put your API Key here

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_CRED_PATH
os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

AUDIO_IN_RATE = 16000
AUDIO_OUT_RATE = 24000


# ==========================================
# 🧠 1. KNOWLEDGE BASE (FAISS TOOL)
# ==========================================
class HorusKnowledgeBase:
    def __init__(self):
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        self.embed_model = TextEmbeddingModel.from_pretrained("text-multilingual-embedding-002")
        self.index = None
        self.docs = []
        self._build_index()

    def _build_index(self):
        try:
            with open(KB_PATH, "r", encoding="utf-8") as f:
                records = json.load(f)
            for rec in records:
                self.docs.append(rec.get("text", ""))

            if self.docs:
                embs = self.embed_model.get_embeddings(self.docs)
                vecs = np.array([e.values for e in embs], dtype=np.float32)
                faiss.normalize_L2(vecs)
                self.index = faiss.IndexFlatIP(vecs.shape[1])
                self.index.add(vecs)
                logger.info(f"RAG Built with {len(self.docs)} chunks.")
        except Exception as e:
            logger.error(f"KB Error: {e}")

    def search(self, query: str) -> str:
        if not query: return "No data available."
        logger.info(f"🔍 [Tool Execution] Searching Knowledge Base for: '{query}'")
        if not self.index: return "No data available."

        qvec = np.array([self.embed_model.get_embeddings([query])[0].values], dtype=np.float32)
        faiss.normalize_L2(qvec)
        _, idxs = self.index.search(qvec, 2)

        results = [self.docs[i] for i in idxs[0] if i != -1]
        res_str = "\n".join(results) if results else "No information found on this topic."
        return str(res_str)[:2000]


kb = HorusKnowledgeBase()


# ==========================================
# 🚀 2. ROS 2 MOVEMENT CONTROLLER (TOOL)
# ==========================================
def start_moving_to_next_exhibit() -> str:
    logger.info("🤖 [Tool Execution] ROS 2 Navigation Command: Moving to next exhibit...")
    if ROS_ENABLED:
        try:
            node = rclpy.create_node('horus_brain_node')
            pub = node.create_publisher(String, '/tour_commands', 10)
            msg = String()
            msg.data = "MOVE_NEXT"
            pub.publish(msg)
            node.destroy_node()
            return "Robot is now moving. Ask the tourists to follow you."
        except Exception as e:
            logger.error(f"ROS Error: {e}")
            return "Error moving robot."
    else:
        return "Simulation: Robot moved to the next exhibit."


# ==========================================
# 🛠️ 3. THE ROBUST GEMINI LIVE CLASS
# ==========================================
class GeminiLive:
    """
    Handles the interaction with the Gemini Live API based on robust community patterns.
    """

    def __init__(self, api_key, model, input_sample_rate, tools=None, tool_mapping=None):
        self.api_key = api_key
        self.model = model
        self.input_sample_rate = input_sample_rate
        self.client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
        self.tools = tools or []
        self.tool_mapping = tool_mapping or {}

    async def start_session(self, audio_input_queue, text_input_queue, audio_output_callback,
                            audio_interrupt_callback=None):

        HORUS_SYSTEM_INSTRUCTION = """
        **Persona:**
        You are Horus, an enthusiastic, warm, and highly engaging tour guide robot working in the Grand Egyptian museum. You speak exactly like a native Egyptian. Your default language is Egyptian Arabic, and you should use natural Egyptian phrasing, warmth, and humor. You seamlessly switch to other languages ONLY if a tourist speaks to you in that language or explicitly requests it, though you can playfully sprinkle in foreign terms if it fits the context. Your primary role is a storyteller; you bring history to life.

        **Conversational Rules:**

        1. **The Greeting:** Start the tour with a delightful, highly welcoming Egyptian greeting and immediately introduce the first piece. 

        2. **The Storytelling Loop:** For every exhibit, you must use the 'search_knowledge_base' tool to retrieve the facts. Tell a compelling story covering all the important information about the piece. You are encouraged to add funny, lighthearted facts, but you must be 100% certain those facts are historically accurate. 

        3. **Handling Unknowns:** If a tourist asks a question and the 'search_knowledge_base' tool returns no information, do not hallucinate or guess. Instead, make up a lighthearted, funny Egyptian joke about why you don't know the answer.

        4. **Moving to the Next Exhibit:** At the end of your story about a piece, always ask the tourists if they are ready to move on. If a tourist asks to move to the next piece, you may occasionally double-check their readiness in a playful, indirect way (for example: "مش عايز تعرف اكتر عن القطعة دي قبل ما نتحرك؟"). 

        5. **Triggering Movement:** Once the tourist confirms they are ready to proceed, you must call the 'start_moving_to_next_exhibit' tool. Let the model know that it's OK to repeat this conversational storytelling loop for as long as the user wants.

        **General Guidelines:** Keep your pacing conversational and natural for spoken audio. Do not overwhelm the user with a giant wall of text; tell the story naturally. Every response should be a net-new addition to the tour, not a recap of what the user just said. 

        **Guardrails:**
        * **Hate Speech:** Anything that promotes racism, hatred, or discrimination is strictly off-limits. Unmistakably shut down these conversations.
        * **Out of Bounds/Danger:** If a tourist asks you to do something physically dangerous (e.g., crashing into a case) or completely outside your scope as a museum robot (e.g., ordering food), politely but firmly refuse by explaining that it is dangerous or strictly off-limits.
        """

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
            system_instruction=types.Content(parts=[types.Part.from_text(text=HORUS_SYSTEM_INSTRUCTION)]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",  # Let Gemini handle silence detection
            ),
            tools=self.tools,
        )

        logger.info(f"Connecting to Gemini Live API with model={self.model}")
        try:
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                logger.info("✅ Gemini Live session opened successfully")

                # --- AUDIO SEND TASK ---
                async def send_audio():
                    try:
                        while True:
                            chunk = await audio_input_queue.get()
                            await session.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={self.input_sample_rate}")
                            )
                    except asyncio.CancelledError:
                        logger.debug("send_audio task cancelled")
                    except Exception as e:
                        logger.error(f"send_audio error: {e}")

                # --- TEXT SEND TASK ---
                async def send_text():
                    try:
                        while True:
                            text = await text_input_queue.get()
                            logger.info(f"Sending text to Gemini: {text}")
                            await session.send_realtime_input(text=text)
                    except asyncio.CancelledError:
                        logger.debug("send_text task cancelled")
                    except Exception as e:
                        logger.error(f"send_text error: {e}")

                event_queue = asyncio.Queue()

                # --- RECEIVE LOOP TASK ---
                async def receive_loop():
                    try:
                        while True:  # 🔥 THE MAGIC BULLET: Keeps iterator alive
                            async for response in session.receive():

                                server_content = getattr(response, "server_content", None)
                                tool_call = getattr(response, "tool_call", None)

                                if server_content:
                                    # Audio playback
                                    model_turn = getattr(server_content, "model_turn", None)
                                    if model_turn:
                                        for part in getattr(model_turn, "parts", []):
                                            inline_data = getattr(part, "inline_data", None)
                                            if inline_data:
                                                if inspect.iscoroutinefunction(audio_output_callback):
                                                    await audio_output_callback(inline_data.data)
                                                else:
                                                    audio_output_callback(inline_data.data)

                                    # Transcriptions
                                    in_trans = getattr(server_content, "input_transcription", None)
                                    if in_trans and in_trans.text:
                                        await event_queue.put({"type": "user_transcription", "text": in_trans.text})

                                    out_trans = getattr(server_content, "output_transcription", None)
                                    if out_trans and out_trans.text:
                                        await event_queue.put({"type": "gemini_transcription", "text": out_trans.text})

                                    if getattr(server_content, "turn_complete", False):
                                        await event_queue.put({"type": "turn_complete"})

                                    if getattr(server_content, "interrupted", False):
                                        if audio_interrupt_callback:
                                            if inspect.iscoroutinefunction(audio_interrupt_callback):
                                                await audio_interrupt_callback()
                                            else:
                                                audio_interrupt_callback()
                                        await event_queue.put({"type": "interrupted"})

                                # Handle Tools safely in executor
                                if tool_call:
                                    function_responses = []
                                    fcs = getattr(tool_call, "function_calls", [])
                                    for fc in fcs:
                                        func_name = getattr(fc, "name", "")
                                        args = getattr(fc, "args", {}) or {}

                                        if func_name in self.tool_mapping:
                                            try:
                                                tool_func = self.tool_mapping[func_name]
                                                if inspect.iscoroutinefunction(tool_func):
                                                    result = await tool_func(**args)
                                                else:
                                                    loop = asyncio.get_running_loop()
                                                    result = await loop.run_in_executor(None, lambda: tool_func(**args))
                                            except Exception as e:
                                                result = f"Error: {e}"

                                            function_responses.append(types.FunctionResponse(
                                                name=func_name,
                                                id=fc.id,
                                                response={"result": result}
                                            ))
                                            await event_queue.put({"type": "tool_call", "name": func_name, "args": args,
                                                                   "result": result})

                                    if function_responses:
                                        await session.send_tool_response(function_responses=function_responses)

                            logger.debug("Gemini receive iterator completed, re-entering receive loop")

                    except asyncio.CancelledError:
                        logger.debug("receive_loop task cancelled")
                    except Exception as e:
                        logger.error(f"receive_loop error: {e}")
                        await event_queue.put({"type": "error", "error": f"{type(e).__name__}: {e}"})
                    finally:
                        await event_queue.put(None)

                # Start the tasks
                send_audio_task = asyncio.create_task(send_audio())
                send_text_task = asyncio.create_task(send_text())
                receive_task = asyncio.create_task(receive_loop())

                # Yield events back to the main application
                try:
                    while True:
                        event = await event_queue.get()
                        if event is None:
                            break
                        if isinstance(event, dict) and event.get("type") == "error":
                            yield event
                            break
                        yield event
                finally:
                    logger.info("Cleaning up Gemini Live session tasks")
                    send_audio_task.cancel()
                    send_text_task.cancel()
                    receive_task.cancel()

        except Exception as e:
            logger.error(f"Gemini Live session connection error: {e}")
            raise
        finally:
            logger.info("Gemini Live session closed")


# ==========================================
# 🎤 4. APPLICATION ENTRY POINT
# ==========================================
async def main():
    print("✨ Starting Horus-Bot Application Engine...")

    # Define the tools exactly as Gemini expects them
    tool_declarations = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="search_knowledge_base",
                description="Use this to look up factual information about museum exhibits when the user asks a question.",
                parameters={"type": "OBJECT", "properties": {"query": {"type": "STRING"}}, "required": ["query"]}
            ),
            types.FunctionDeclaration(
                name="start_moving_to_next_exhibit",
                description="Call this ONLY when the tourist explicitly says they are ready to go to the next piece.",
                parameters={"type": "OBJECT", "properties": {}}
            )
        ]
    )

    # Map the declaration names to our actual python functions
    tool_map = {
        "search_knowledge_base": kb.search,
        "start_moving_to_next_exhibit": start_moving_to_next_exhibit
    }

    gemini = GeminiLive(
        api_key=GEMINI_API_KEY,
        model="gemini-3.1-flash-live-preview",
        input_sample_rate=AUDIO_IN_RATE,
        tools=[tool_declarations],
        tool_mapping=tool_map
    )

    loop = asyncio.get_running_loop()
    audio_in_queue = asyncio.Queue()
    text_in_queue = asyncio.Queue()
    audio_out_queue = queue.Queue()
    audio_buffer = bytearray()
    
    # --- ROS 2 Background Thread ---
    def ros2_subscriber_thread():
        if not ROS_ENABLED:
            return
            
        try:
            rclpy.init()
        except RuntimeError:
            pass # Context already initialized
            
        listener_node = rclpy.create_node('horus_listener_node')
        
        def exhibit_callback(msg):
            prompt = f"We have safely arrived at the {msg.data}. Please naturally tell the story about this exhibit."
            logger.info(f"ROS 2 Trigger received: {msg.data}. Injecting prompt to Gemini!")
            loop.call_soon_threadsafe(text_in_queue.put_nowait, prompt)
            
        listener_sub = listener_node.create_subscription(String, '/arrived_exhibit', exhibit_callback, 10)
        logger.info("ROS 2 background subscriber thread started listening on /arrived_exhibit")
        
        try:
            rclpy.spin(listener_node)
        finally:
            listener_node.destroy_node()
            rclpy.shutdown()

    if ROS_ENABLED:
        threading.Thread(target=ros2_subscriber_thread, daemon=True).start()

    

    # --- Hardware Audio Callbacks ---
    def mic_callback(indata, frames, time_info, status):
        loop.call_soon_threadsafe(audio_in_queue.put_nowait, indata.tobytes())

    def speaker_callback(outdata, frames, time_info, status):
        nonlocal audio_buffer
        bytes_needed = frames * 2
        while True:
            try:
                chunk = audio_out_queue.get_nowait()
                if chunk == b"CLEAR":
                    audio_buffer.clear()
                    continue
                audio_buffer.extend(chunk)
            except queue.Empty:
                break

        if len(audio_buffer) >= bytes_needed:
            outdata[:] = np.frombuffer(audio_buffer[:bytes_needed], dtype=np.int16).reshape(-1, 1)
            del audio_buffer[:bytes_needed]
        else:
            avail = len(audio_buffer) // 2
            if avail > 0:
                outdata[:avail] = np.frombuffer(audio_buffer[:avail * 2], dtype=np.int16).reshape(-1, 1)
                outdata[avail:] = 0
                del audio_buffer[:]
            else:
                outdata.fill(0)

    # --- Session Callbacks ---
    def on_audio_output(chunk_bytes):
        audio_out_queue.put_nowait(chunk_bytes)

    def on_audio_interrupt():
        with audio_out_queue.mutex:
            audio_out_queue.queue.clear()
        audio_out_queue.put_nowait(b"CLEAR")
        print("\n[Tourist Interrupted Horus!]")

    print("🎙️ Activating hardware audio streams...")
    in_stream = sd.InputStream(samplerate=AUDIO_IN_RATE, channels=1, dtype='int16', blocksize=1024,
                               callback=mic_callback)
    out_stream = sd.OutputStream(samplerate=AUDIO_OUT_RATE, channels=1, dtype='int16', callback=speaker_callback)

    with in_stream, out_stream:
        while True:  # Auto-reconnect wrap
            try:
                print("\n🦅 Horus is waking up and listening...")

                # Kick off the tour with the greeting
                text_in_queue.put_nowait("The tour has just started. Greet the tourists warmly in Egyptian Arabic.")

                # Consume events from the robust session
                async for event in gemini.start_session(
                        audio_input_queue=audio_in_queue,
                        text_input_queue=text_in_queue,
                        audio_output_callback=on_audio_output,
                        audio_interrupt_callback=on_audio_interrupt
                ):
                    if event["type"] == "gemini_transcription":
                        print(event["text"], end=" ", flush=True)
                    elif event["type"] == "user_transcription":
                        print(f"\n👤 Tourist: {event['text']}")
                    elif event["type"] == "turn_complete":
                        print("\n🎤 (Listening...)")
                    elif event["type"] == "error":
                        print(f"\n🔥 Session Error Event: {event['error']}")
                        break  # Break out to auto-reconnect

            except Exception as e:
                print(f"\nConnection dropped. Reconnecting in 3s... ({e})")
                await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTour ended by user.")