# Velociraptor

An intelligent document processing system that transforms PDF documents into a searchable knowledge graph using AI-powered extraction and hierarchical summarization. Named after the clever, systematic hunters from Jurassic Park, Velociraptor intelligently tracks and retrieves information from your document collections.

## Overview

Velociraptor implements an advanced agentic search RAG (Retrieval-Augmented Generation) approach that goes beyond traditional document chunking. Instead of simply splitting documents into arbitrary chunks, Velociraptor:

1. **Extracts structured content** from PDF pages using Google Gemini's multimodal capabilities
2. **Creates hierarchical summaries** at multiple abstraction levels through progressive aggregation
3. **Builds a knowledge graph** in Neo4j that preserves document structure and relationships
4. **Enables semantic search** through embeddings and traditional keyword search
5. **Maintains context** by storing the complete document hierarchy from individual pages to high-level summaries

This approach allows for more intelligent retrieval that understands document structure, context, and relationships between different sections.

## Architecture

### Core Components

- **PDF Processing**: Converts PDFs to images and extracts content using Gemini 2.5 Flash
- **Hierarchical Summarization**: Creates multi-level summary trees through progressive aggregation
- **Knowledge Graph**: Stores documents, pages, summaries, and chunks in Neo4j with preserved relationships
- **Embedding Pipeline**: Generates semantic embeddings for chunks using Gemini embedding model
- **Search Infrastructure**: Combines vector similarity search with full-text search capabilities

### Data Flow

```
PDF Documents → Page Images → Content Extraction → Hierarchical Summarization → Text Chunking → Embeddings → Neo4j Knowledge Graph
```

### Knowledge Graph Structure

The system creates a rich graph structure with the following node types:
- **Document**: Top-level document metadata
- **Page**: Individual PDF pages with extracted content
- **Summary**: Hierarchical summaries at different abstraction levels
- **Chunk**: Text chunks with embeddings for semantic search

Relationships include `CONTAINS`, `PART_OF`, `SUMMARIZES`, `NEXT`, and `PREVIOUS` to maintain document structure and enable intelligent traversal.

## Setup and Installation

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Google Gemini API key

### 1. Clone and Setup Environment

```bash
git clone <repository-url>
cd velociraptor
```

### 2. Install Dependencies

```bash
pip install -e .
```

### 3. Configure Environment

```bash
cp env.example .env
# Edit and add secret values

cp env.docker.example .env.docker
# Edit and add secret values
```

### 4. Start Neo4j Database

```bash
docker-compose up -d
```

This starts Neo4j with:
- Web interface: http://localhost:7474
- Bolt connection: bolt://localhost:7687
- Username: `neo4j`
- Password: `neo4j_password`

### 5. Create Document Directory

```bash
mkdir -p files/documents
```

### 6. Add PDF Documents

Place your PDF files in the `files/documents/` directory:

```bash
cp your-documents.pdf files/documents/
```

### 7. Process Documents

```bash
python -m src.velociraptor.scripts.process_documents
```

This will:
- Convert PDFs to images
- Extract content using Gemini
- Create hierarchical summaries
- Generate embeddings
- Store everything in Neo4j
- Create search indexes

## MCP Server Integration

Velociraptor is designed to work with MCP (Model Context Protocol) clients like Claude Desktop for agentic search capabilities.

### Required MCP Servers

To enable full agentic search functionality, configure these MCP servers in your MCP client:

#### Docker Image Download

First, pull the required Docker image for the filesystem MCP server:

```bash
docker pull mcp/filesystem
```

#### 1. Neo4j MCP Server

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "neo4j": {
      "command": "uvx",
      "args": [
          "mcp-neo4j-cypher",
          "--db-url",
          "neo4j://localhost:7687",
          "--username",
          "neo4j",
          "--password",
          "neo4j_password"
      ]
    }
  }
}
```

#### 2. File System MCP Server

For accessing page images and document metadata:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "--mount",
        "type=bind,src=/path/to/your/checkout/velociraptor/files,dst=/projects/velociraptor,ro",
        "mcp/filesystem",
        "/projects"
      ]
    }
  }
}
```

**Purpose**: Access original page images (JPG format) when text extraction may be insufficient for graphics, charts, tables, or diagrams. Essential for visual verification and displaying page images to users upon request.

#### 3. Semantic Search MCP Server

**REQUIRED**: This server enables fast semantic search by combining query embedding and vector similarity search in a single operation.

The semantic search MCP server is now available as a Docker container. **You must build the Docker image first:**

```bash
# Build the Docker image for the semantic search MCP server
docker-compose build semantic-search
```

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "semantic-search": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--env-file",
        "/path/to/your/checkout/velociraptor/.env.docker",
        "velociraptor/semantic-search:latest"
      ]
    }
  }
}
```

Alternatively, you can still run it directly with Python if preferred:

```bash
# Alternative: Start the semantic search MCP server directly
python -m src.velociraptor.mcp.semantic_search_mcp
```

```json
{
  "mcpServers": {
    "semantic-search": {
      "command": "python",
      "args": [
        "-m",
        "src.velociraptor.mcp.semantic_search_mcp"
      ],
      "cwd": "/path/to/your/checkout/velociraptor"
    }
  }
}
```

**Purpose**: Performs complete semantic search by automatically embedding queries using the same Gemini embedding model (`gemini-embedding-001`) and executing vector similarity search against the Neo4j knowledge graph. This eliminates the need to send large embedding vectors over MCP, significantly improving search performance.

### Claude Desktop Configuration

Edit your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "neo4j": {
      "command": "uvx",
      "args": [
          "mcp-neo4j-cypher",
          "--db-url",
          "neo4j://localhost:7687",
          "--username",
          "neo4j",
          "--password",
          "neo4j_password"
      ]
    },
    "filesystem": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "--mount",
        "type=bind,src=/path/to/your/checkout/velociraptor/files,dst=/projects/velociraptor,ro",
        "mcp/filesystem",
        "/projects"
      ]
    },
    "semantic-search": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--env-file",
        "/path/to/your/checkout/velociraptor/.env.docker",
        "velociraptor/semantic-search:latest"
      ]
    }
  }
}
```

### Agentic Search Queries

With MCP servers configured, you can perform sophisticated searches like:

```
"Find all documents that discuss machine learning algorithms and show me the hierarchical summaries"

"Search for information about data privacy regulations and trace back to the original document pages"

"What are the key themes across all processed documents? Show me the high-level summaries."

"Find chunks related to 'neural networks' and show me their document context"
```

The AI agent can:
- Query the knowledge graph for semantic relationships
- Navigate document hierarchies intelligently
- Combine multiple search strategies ("hunting in packs")
- Access original document metadata and page images
- Provide contextual results with complete source attribution
- Work with subtle Jurassic Park personality while maintaining professionalism

### Source Attribution

Every response includes complete source citations with:
- Document titles and UUIDs for file access
- Specific page numbers when content comes from particular pages  
- Structured citations that enable immediate file opening when requested

**Example**: `[Document: "Q3 Financial Report", Page 12 (UUID: doc-456-789)]`

## Database Schema

### Node Types

- **Document**: `{id, title, file_path, processed_at}`
- **Page**: `{id, page_number, content, summary, image_path}`
- **Summary**: `{id, content, height, page_range}`
- **Chunk**: `{id, content, chunk_index, embedding}`

### Relationship Types

- **CONTAINS**: Document contains Pages, Summaries contain Chunks
- **PART_OF**: Pages/Summaries are part of Documents
- **SUMMARIZES**: Summaries summarize Pages or other Summaries
- **NEXT/PREVIOUS**: Sequential relationships between Pages and Summaries

### Indexes

- Vector index on chunk embeddings (3072 dimensions)
- Full-text search on content fields
- Property indexes on IDs and metadata

## Development

### Project Structure

```
src/velociraptor/
├── db/           # Neo4j database operations
├── llm/          # Gemini LLM integration
├── models/       # Pydantic data models
├── split/        # Text chunking and processing
├── summarize/    # Hierarchical summarization
├── scripts/      # Processing pipelines
├── prompts/      # LLM prompts and templates
└── utils/        # Logging and utilities
```

### Adding New Document Types

To support additional document formats:
1. Create new splitter in `src/velociraptor/split/`
2. Add processing logic to `src/velociraptor/scripts/process_documents.py`
3. Update models if needed for new metadata

### Customizing Summarization

Modify prompts in `src/velociraptor/prompts/` to adjust:
- Extraction detail level
- Summary style and focus
- Structured output format

## Dependencies

- **PyMuPDF**: PDF processing and conversion
- **Neo4j**: Graph database for knowledge storage
- **Google GenAI**: Gemini LLM for extraction and embeddings
- **Langchain**: Text splitting utilities
- **Pydantic**: Data validation and schema management
- **aiofiles**: Async file operations

## License

[Add your license information here]