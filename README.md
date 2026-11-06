# Horus Bot: Autonomous Smart Tour Guide Robot

## Overview
Horus is a fully integrated, autonomous smart tour guide robot designed for museum and exhibition environments. Going beyond standard point-to-point navigation, Horus serves as an interactive, AI-powered educational companion for visitors.

This project demonstrates a complex integration of modern robotics and advanced natural language processing. By combining the robust hardware control of ROS 2 with a custom Retrieval-Augmented Generation (RAG) pipeline, Horus delivers a complete, end-to-end smart tourism solution.

## Tech Stack
* **Robotics Middleware:** ROS 2 (Humble/Iron)
* **Simulation & Visualization:** Gazebo, RViz
* **Navigation & Mapping:** Nav2, SLAM Toolbox
* **AI & NLP:** Python, LangChain, Large Language Models (LLMs), RAG Architecture
* **Sensor Integration:** LiDAR (RPLidar), Depth Cameras, Ultrasonic sensors

## Core Capabilities

### Autonomous Mobility & Robotics
* **Dynamic Mapping:** Capable of generating 2D maps of unknown environments on the fly using SLAM.
* **Advanced Path Planning:** Utilizes the Nav2 stack for dynamic routing, waypoint navigation, and real-time obstacle avoidance in complex environments.
* **Multi-Sensor Fusion:** Processes concurrent data streams from LiDAR, depth cameras, and ultrasonic sensors to perceive its surroundings and navigate safely.
* **Interactive Tracking:** Includes a dynamic ball-tracking module and manual joystick override, demonstrating computer vision capabilities and safe teleoperation.

### AI-Powered Tour Guide
* **Conversational Interface:** Features a dedicated graphical user interface (`caption_ui.py`) that allows visitors to interact with the robot using natural language.
* **RAG Knowledge Base:** Employs a Retrieval-Augmented Generation pipeline (`TourGuideRag.py`) to ground the LLM's responses. This ensures the robot provides highly accurate, fact-based historical information without hallucination.
* **Real-time Integration:** The main application logic (`live_horus.py`) bridges the AI backend with the robot's physical state, enabling dynamic, curator-level interactions on the fly.

## Project Architecture

The repository is organized to clearly separate the ROS 2 hardware/simulation configurations from the high-level AI application logic:

```text
horus_bot/
├── config/              # Tuning parameters for Nav2, RViz, SLAM, and hardware controllers
├── description/         # URDF/Xacro files defining the robot's physical model and kinematics
├── launch/              # ROS 2 launch files orchestrating simulation, navigation, and sensors
├── maps/                # Generated environment data (.pgm, .yaml, and posegraphs)
├── scripts/             # Core AI pipeline and High-Level Application Logic
│   ├── Horus_Database/  # Unstructured text corpus used for the RAG knowledge base
│   ├── TourGuideRag.py  # RAG implementation handling document retrieval and LLM prompting
│   ├── caption_ui.py    # Graphical interface for visitor inquiries
│   ├── live_horus.py    # Main integration node managing the AI persona and state
│   └── ...              # Auxiliary ROS 2 nodes (waypoints, ultrasonic processing, etc.)
└── worlds/              # Custom Gazebo simulation environments for testing
```

## Data Architecture: The Horus Database
The intelligence of the robot is modular and easily scalable. The `Horus_Database` directory serves as the textual corpus for the RAG pipeline, pre-loaded with detailed historical texts regarding ancient Egyptian artifacts (e.g., the treasures of Tutankhamun, Ramesses II). 

The system is designed for seamless deployment to new museums: updating the robot's knowledge requires no code changes. A museum curator simply adds new text files to the database, which the application automatically ingests, chunks, and vectorizes to answer future visitor questions.
