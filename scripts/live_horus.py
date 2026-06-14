#!/usr/bin/env python3

import asyncio
import os
import json
import uuid
import numpy as np
import sounddevice as sd
import faiss
import queue
import threading
import traceback
import inspect
import logging
import yaml

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
KB_PATH = r"src/articubot_one/scripts/TourGuideRag_V02.txt"
GEMINI_API_KEY = "REDACTED"  # Put your API Key here

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_CRED_PATH
os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

AUDIO_IN_RATE = 16000
AUDIO_OUT_RATE = 24000

def get_exhibit_names():
    try:
        with open('/home/abdelrahman/project/src/articubot_one/config/waypoints.yaml', 'r') as file:
            data = yaml.safe_load(file)
            return [wp['name'] for wp in data.get('waypoints', [])]
    except Exception as e:
        logger.error(f"Failed to read waypoints.yaml: {e}")
        return []

EXHIBIT_ORDER = get_exhibit_names()
EXHIBIT_LIST_STR = ", ".join(EXHIBIT_ORDER) if EXHIBIT_ORDER else "Unknown"

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
        return str(res_str)[:8000]


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


def go_to_specific_exhibit(exhibit_name: str) -> str:
    logger.info(f"🤖 [Tool Execution] ROS 2 Navigation Command: Moving specifically to {exhibit_name}...")
    if ROS_ENABLED:
        try:
            node = rclpy.create_node('horus_brain_node_goto')
            pub = node.create_publisher(String, '/tour_commands', 10)
            msg = String()
            msg.data = f"GOTO: {exhibit_name}"
            pub.publish(msg)
            node.destroy_node()
            return f"Robot is now skipping other exhibits and moving to {exhibit_name}. Ask the tourists to follow you."
        except Exception as e:
            logger.error(f"ROS Error: {e}")
            return "Error moving robot."
    else:
        return f"Simulation: Robot skipping to {exhibit_name}."


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

        HORUS_SYSTEM_INSTRUCTION = f"""
        **Persona:**
        You are Horus (حورس), a multilingual enthusiastic, warm, and highly engaging tour guide robot working in the Grand Egyptian museum. You speak exactly like a native Egyptian.  and you should use natural Egyptian phrasing, warmth, and humor. You seamlessly switch to other languages if a tourist speaks to you in that language or explicitly requests it, though you can playfully sprinkle in foreign terms if it fits the context. Your primary role is a storyteller; you bring history to life.

        **Tour Structure & Awareness:**
        - The tour consists of the following exhibits in order: {EXHIBIT_LIST_STR}.
        - You will be notified when you arrive at an exhibit. Always keep track of where you are in the tour and if it is the last exhibit.

        **Conversational Rules:**

        1. **The Greeting:** Start the tour with a delightful, highly welcoming Egyptian greeting and immediately introduce the first piece. 

        2. **The Storytelling Loop:** For every exhibit, you must use the 'search_knowledge_base' tool to retrieve the facts. Tell a compelling story covering every single information you retrieved about the piece. You are encouraged to add funny, lighthearted facts, but you must be 100% certain those facts are historically accurate. 

        3. **Handling Unknowns:** If a tourist asks a question and the 'search_knowledge_base' tool returns no information, do not hallucinate or guess. Instead, make up a lighthearted, funny Egyptian joke about why you don't know the answer.

        4. **Moving to the Next Exhibit:** At the end of your story about a piece, always ask the tourists if they are ready to move on. If a tourist asks to move to the next piece, you may occasionally double-check their readiness in a playful, indirect way (for example: "مش عايز تعرف اكتر عن القطعة دي قبل ما نتحرك؟"). 
        If it is the last exhibit on the tour, conclude the tour gracefully instead of asking to move on.

        5. **Triggering Movement:** Once the tourist confirms they are ready to proceed, you must call the 'start_moving_to_next_exhibit' tool. Let the model know that it's OK to repeat this conversational storytelling loop for as long as the user wants. If the tourist explicitly requests to skip the rest and go straight to a specific artifact by name, call the 'go_to_specific_exhibit' tool with that name.

        **General Guidelines:** Keep your pacing conversational and natural for spoken audio. Do not overwhelm the user with a giant wall of text; tell the story naturally. Every response should be a net-new addition to the tour, not a recap of what the user just said. 

        **Guardrails:**
        * **Hate Speech:** Anything that promotes racism, hatred, or discrimination is strictly off-limits. Unmistakably shut down these conversations.
        * **Out of Bounds/Danger:** If a tourist asks you to do something physically dangerous (e.g., crashing into a case) or completely outside your scope as a museum robot (e.g., ordering food), politely but firmly refuse by explaining that it is dangerous or strictly off-limits.
        """

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Achird")
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
            ),
            types.FunctionDeclaration(
                name="go_to_specific_exhibit",
                description="Call this ONLY when the tourist explicitly asks to skip ahead and go straight to a specific artifact by name.",
                parameters={"type": "OBJECT", "properties": {"exhibit_name": {"type": "STRING", "description": "The name of the exhibit to go to."}}, "required": ["exhibit_name"]}
            )
        ]
    )

    # Map the declaration names to our actual python functions
    tool_map = {
        "search_knowledge_base": kb.search,
        "start_moving_to_next_exhibit": start_moving_to_next_exhibit,
        "go_to_specific_exhibit": go_to_specific_exhibit
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
    # Track whether we're waiting for a question answer
    _question_pending = {'active': False, 'text': ''}
    
    # --- ROS 2 Background Thread ---
    def ros2_subscriber_thread():
        if not ROS_ENABLED:
            return
            
        try:
            rclpy.init()
        except RuntimeError:
            pass # Context already initialized
            
        listener_node = rclpy.create_node('horus_listener_node')
        globals()['caption_pub'] = listener_node.create_publisher(String, '/horus_captions', 10)
        globals()['tour_events_pub'] = listener_node.create_publisher(String, '/tour_events', 10)
        globals()['question_events_pub'] = listener_node.create_publisher(String, '/question_events', 10)

        def _publish_tour_event(event_type: str, payload: dict = None):
            """Helper to publish a JSON event to /tour_events."""
            if 'tour_events_pub' not in globals():
                return
            event = {
                'eventId': f'evt_{uuid.uuid4().hex[:12]}',
                'type': event_type,
                'payload': payload or {},
            }
            msg = String()
            msg.data = json.dumps(event)
            globals()['tour_events_pub'].publish(msg)
            logger.info(f"Published tour_event: {event_type}")

        def _publish_question_event(event_type: str, text: str = ''):
            """Helper to publish a JSON event to /question_events."""
            if 'question_events_pub' not in globals():
                return
            event = {
                'eventId': f'evt_{uuid.uuid4().hex[:12]}',
                'type': event_type,
                'text': text,
            }
            msg = String()
            msg.data = json.dumps(event)
            globals()['question_events_pub'].publish(msg)
            logger.info(f"Published question_event: {event_type}")

        # Store helpers in globals so the event loop can access them
        globals()['_publish_tour_event'] = _publish_tour_event
        globals()['_publish_question_event'] = _publish_question_event

        def exhibit_callback(msg):
            try:
                data = json.loads(msg.data)
                name = data.get('name', 'unknown exhibit')
                is_last = data.get('is_last', False)
                current_idx = data.get('index', 0)
                total = data.get('total', 0)
            except json.JSONDecodeError:
                name = msg.data
                is_last = False
                current_idx = 0
                total = 0

            prompt = f"We have safely arrived at the {name} (Exhibit {current_idx} of {total}). Please naturally tell the story about this exhibit."
            if is_last:
                prompt += " This is the last exhibit on our tour! After telling the story, gracefully conclude the tour."
            else:
                prompt += " After telling the story, remember to ask the tourists if they are ready to move on."
                
            logger.info(f"ROS 2 Trigger received: {name}. Injecting prompt to Gemini!")
            loop.call_soon_threadsafe(text_in_queue.put_nowait, prompt)
            
        listener_sub = listener_node.create_subscription(String, '/arrived_exhibit', exhibit_callback, 10)

        def cloud_command_callback(msg):
            """Handle commands forwarded by the cloud bridge."""
            try:
                cmd = json.loads(msg.data)
            except json.JSONDecodeError:
                return

            cmd_type = cmd.get('type', '')
            payload = cmd.get('payload', {})

            if cmd_type == 'app_question':
                question_text = payload.get('text', '')
                if question_text:
                    logger.info(f"Cloud command: app_question — '{question_text}'")
                    _publish_question_event('question_received', question_text)
                    _question_pending['active'] = True
                    _question_pending['text'] = question_text
                    loop.call_soon_threadsafe(
                        text_in_queue.put_nowait,
                        f"A tourist sent a text question from the app: \"{question_text}\". Please answer it."
                    )
            elif cmd_type == 'start_tour':
                logger.info("Cloud command: start_tour — injecting greeting prompt")
                _publish_tour_event('tour_started')
                loop.call_soon_threadsafe(
                    text_in_queue.put_nowait,
                    "The tour has just started. Greet the tourists warmly in Egyptian Arabic."
                )
            elif cmd_type == 'end_tour':
                logger.info("Cloud command: end_tour — injecting goodbye prompt")
                loop.call_soon_threadsafe(
                    text_in_queue.put_nowait,
                    "The tour has ended. Please say a warm goodbye to the tourists."
                )
                _publish_tour_event('tour_ended')
            elif cmd_type == 'skip':
                logger.info("Cloud command: skip — telling Horus to wrap up")
                loop.call_soon_threadsafe(
                    text_in_queue.put_nowait,
                    "The tourists want to skip to the next exhibit. Briefly acknowledge and let them know you're moving on."
                )
            # Other command types (find_robot, etc.) handled by waypoint_node

        cloud_cmd_sub = listener_node.create_subscription(
            String, '/cloud_commands', cloud_command_callback, 10)

        logger.info("ROS 2 background subscriber thread started listening on /arrived_exhibit and /cloud_commands")
        
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
                if ROS_ENABLED and '_publish_tour_event' in globals():
                    globals()['_publish_tour_event']('tour_started')

                # Consume events from the robust session
                async for event in gemini.start_session(
                        audio_input_queue=audio_in_queue,
                        text_input_queue=text_in_queue,
                        audio_output_callback=on_audio_output,
                        audio_interrupt_callback=on_audio_interrupt
                ):
                    if event["type"] == "gemini_transcription":
                        print(event["text"], end=" ", flush=True)
                        if ROS_ENABLED and 'caption_pub' in globals():
                            msg = String()
                            msg.data = f"APPEND:{event['text']}"
                            globals()['caption_pub'].publish(msg)
                    elif event["type"] == "user_transcription":
                        print(f"\n👤 Tourist: {event['text']}")
                    elif event["type"] == "turn_complete":
                        print("\n🎤 (Listening...)")
                        if ROS_ENABLED and 'caption_pub' in globals():
                            msg = String()
                            msg.data = "CLEAR:"
                            globals()['caption_pub'].publish(msg)
                        # If we were answering an app question, mark it answered
                        if _question_pending['active']:
                            _question_pending['active'] = False
                            if ROS_ENABLED and '_publish_question_event' in globals():
                                globals()['_publish_question_event']('question_answered')
                    elif event["type"] == "interrupted":
                        if ROS_ENABLED and 'caption_pub' in globals():
                            msg = String()
                            msg.data = "CLEAR:"
                            globals()['caption_pub'].publish(msg)
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