# Quercus Genius

### AI-Powered Academic Planning Assistant Using Model Context Protocol (MCP)

An intelligent academic planning assistant that integrates **Model Context Protocol (MCP), Cohere's North AI platform, Canvas LMS (Quercus), and Google Calendar** to help students manage coursework, track deadlines, and make informed academic decisions through natural-language interactions.

Developed during the **Cohere x WISE Hackathon (January 2026)** at the University of Toronto.

## Overview

Students often manage coursework across multiple platforms, making it difficult to track assignments, monitor grades, and organize their schedules efficiently.

**MCP Student Planner** addresses this challenge by connecting academic information with an AI-powered assistant, enabling students to retrieve course information, organize deadlines, and plan their academic workload through a unified conversational interface.

The project leverages MCP to connect an AI agent with external academic tools and services, allowing natural-language requests to trigger structured data retrieval and planning workflows.

## Key Features

### 1. AI-Powered Academic Assistant
- Uses Cohere's North AI platform for natural-language interactions.
- Enables students to ask questions about courses, assignments, deadlines, and academic progress.
- Uses MCP tools to connect the AI agent with academic data and external services.

### 2. Canvas LMS (Quercus) Integration
- Integrates with the Canvas REST API to retrieve academic information.
- Supports retrieval of course materials, assignments, and deadlines.
- Consolidates academic information across multiple courses into a centralized workflow.

### 3. Automated Assignment Tracking
- Organizes assignments and upcoming deadlines across courses.
- Helps students identify outstanding coursework and prioritize tasks.
- Reduces manual effort required to navigate multiple course pages.

### 4. Google Calendar Integration
- Connects academic deadlines with Google Calendar.
- Supports calendar-based planning and scheduling workflows.
- Helps students coordinate coursework with their existing schedules.

### 5. Academic Performance Insights
- Supports grade tracking and academic performance analysis.
- Enables grade forecasting to help students explore potential outcomes.
- Provides personalized decision support for academic planning.

### 6. Document and PDF Processing
- Extracts relevant information from academic documents and PDFs.
- Integrates document content into academic planning workflows.
- Makes course information accessible through natural-language queries.

## Technology Stack

| Technology | Purpose |
|------------|---------|
| Python | Core application logic and backend integration |
| Model Context Protocol (MCP) | Standardized tool integration and communication |
| Cohere North | LLM-powered conversational agent |
| Canvas LMS REST API | Retrieval of course and assignment information |
| Google Calendar API | Calendar integration and academic scheduling |
| PDF Processing | Extraction of information from academic documents |
| REST APIs | Communication with external academic services |

## System Architecture

The application uses an MCP-based architecture to connect an AI assistant with academic data sources and scheduling tools.

```text
                  Student
                     |
                     v
          Natural Language Query
                     |
                     v
             Cohere North AI
                     |
                     v
              MCP Tool Layer
                     |
        +------------+------------+
        |            |            |
        v            v            v
    Canvas LMS    PDF/Data     Google Calendar
      API         Processing        API
        |            |            |
        +------------+------------+
                     |
                     v
         Academic Data Integration
                     |
                     v
         Personalized AI Response
```

### Workflow

1. **User Request:** A student submits a natural-language question or planning request.
2. **Tool Selection:** The AI agent determines which MCP tools are relevant to the request.
3. **Data Retrieval:** MCP tools retrieve information from Canvas LMS, academic documents, or connected services.
4. **Data Processing:** Retrieved information is processed and structured for analysis.
5. **Response Generation:** The AI assistant provides contextual insights, deadline information, or planning recommendations.
6. **External Actions:** When applicable, integrated tools support calendar scheduling and academic workflow automation.

## Example Use Cases

**Assignment Tracking**
> "What assignments do I have due this week across all my courses?"

**Academic Planning**
> "Help me organize my upcoming assignments and exams."

**Grade Forecasting**
> "What grade do I need on my final exam to achieve my target course grade?"

**Course Information**
> "Summarize the important deadlines for my courses."

**Calendar Integration**
> "Add my upcoming assignment deadlines to Google Calendar."

These examples illustrate the intended natural-language workflows supported by the project's integrations.

## Project Highlights

- Developed a functional AI academic planning prototype during a **22-hour hackathon**, with the core solution built in approximately **6 hours**.
- Implemented Python-based MCP tools to connect an LLM-powered agent with external academic services.
- Designed workflows to consolidate information from **6+ courses and 100+ assignments**.
- Integrated structured academic data and PDF-based course information into natural-language query workflows.
- Explored AI-driven academic planning, automated scheduling, and grade forecasting.

## Getting Started

Clone the repository:

```bash
git clone https://github.com/aria-yang/mcp_student_planner.git
cd mcp_student_planner
```

The application requires appropriate access credentials for its connected services, including Canvas LMS and Google Calendar, as applicable.

Refer to the project's Python source files for the required dependencies, configuration, and execution entry points.

**Security:** API tokens, credentials, and other sensitive configuration values should be kept out of version control.


## Acknowledgements

Developed as part of the **Cohere x WISE Hackathon 2026** at the University of Toronto.

Built using Cohere's North AI platform, Model Context Protocol (MCP), Canvas LMS APIs, and Google Calendar APIs.
