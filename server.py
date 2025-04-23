# server.py
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import os
import xml.etree.ElementTree as ET
import requests
import json

load_dotenv()

# Create an MCP server
mcp = FastMCP("Demo")

claude_api_key = os.getenv("ANTHROPIC_API_KEY")

# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"


# Add code directory as a resource
@mcp.resource("codedir://{path}")
def code_directory(path: str):
    """Handle a code directory as a resource"""
    if not os.path.isdir(path):
        return {"status": "error", "message": "Directory does not exist"}
    
    return {"status": "success", "path": path, "files": os.listdir(path)}


# Tool to update library version in pom.xml
@mcp.tool()
def update_library_version(code_dir: str, library_name: str, new_version: str):
    """Update a specific library version in root pom.xml"""
    pom_path = os.path.join(code_dir, "pom.xml")
    
    if not os.path.exists(pom_path):
        return {"status": "error", "message": "pom.xml not found in the directory"}
    
    try:
        # Register the namespace
        ET.register_namespace('', "http://maven.apache.org/POM/4.0.0")
        tree = ET.parse(pom_path)
        root = tree.getroot()
        
        # Need to handle namespaces in Maven POM
        namespace = {'ns': 'http://maven.apache.org/POM/4.0.0'}
        
        # Find the dependency
        found = False
        old_version = None
        
        for dependency in root.findall(".//ns:dependency", namespace):
            artifact_id = dependency.find("ns:artifactId", namespace)
            
            if artifact_id is not None and artifact_id.text == library_name:
                version = dependency.find("ns:version", namespace)
                if version is not None:
                    old_version = version.text
                    version.text = new_version
                    found = True
                    break
        
        if not found:
            return {"status": "error", "message": f"Library {library_name} not found in pom.xml"}
        
        # Save the changes
        tree.write(pom_path, encoding='utf-8', xml_declaration=True)
        
        return {
            "status": "success", 
            "message": f"Updated {library_name} from {old_version} to {new_version}"
        }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}


# Tool to check compatibility using Claude 3.7 LLM
@mcp.tool()
def check_compatibility(code_dir: str, library_name: str, old_version: str, new_version: str):
    """Check if an upgraded library version is compatible with current code using Claude 3.7"""
    
    # Collect relevant code snippets that use the library
    code_snippets = []
    imports_to_check = []
    
    # For Spring libraries, check for these imports
    if "spring" in library_name.lower():
        imports_to_check = [
            "org.springframework", 
            "springframework",
            "@Controller",
            "@RestController",
            "@Service",
            "@Repository",
            "@Component",
            "@RequestMapping"
        ]
    
    print(f"Scanning for code using {library_name}...")
    found_files = 0
    
    for root, _, files in os.walk(code_dir):
        for file in files:
            if file.endswith(('.java', '.xml', '.properties', '.yml', '.yaml')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                        # Check if this file uses the library
                        is_relevant = False
                        
                        # First check exact library name
                        if library_name in content:
                            is_relevant = True
                            print(f"Found direct reference to {library_name} in {file}")
                        
                        # Then check relevant imports for this library type
                        elif imports_to_check:
                            for import_str in imports_to_check:
                                if import_str in content:
                                    is_relevant = True
                                    print(f"Found import {import_str} in {file}")
                                    break
                        
                        # For pom.xml and other config files, check more broadly
                        elif file.endswith('.xml') and 'dependency' in content and ('spring' in content.lower() or library_name.lower() in content.lower()):
                            is_relevant = True
                            print(f"Found dependency in {file}")
                            
                        if is_relevant:
                            relative_path = os.path.relpath(file_path, code_dir)
                            found_files += 1
                            # Limit snippet size if too large
                            if len(content) > 2000:
                                content = content[:2000] + "... (truncated)"
                            code_snippets.append((relative_path, content))
                            print(f"Added {relative_path} to code snippets")
                except Exception as e:
                    print(f"Error reading file {file}: {str(e)}")
    
    print(f"Found {len(code_snippets)} relevant code files")
    
    if not code_snippets:
        print(f"Warning: No code snippets found that use {library_name}")
        
        # If no specific files found, include at least the pom.xml as context
        pom_path = os.path.join(code_dir, "pom.xml")
        if os.path.exists(pom_path):
            try:
                with open(pom_path, 'r', encoding='utf-8') as f:
                    pom_content = f.read()
                code_snippets.append(("pom.xml", pom_content))
                print("Added pom.xml as fallback")
            except Exception as e:
                print(f"Error reading pom.xml: {str(e)}")
    
    # Prepare prompt for Claude 3.7
    snippets_text = ""
    for file, snippet in code_snippets[:5]:
        snippets_text += f"--- {file} ---\n{snippet}\n\n"
    
    prompt = f"""
    I'm upgrading {library_name} from version {old_version} to {new_version}.
    
    Please analyze if the new version is compatible with our current code.
    Focus on deprecated functions/methods, API changes, deprecated features, and breaking code changes.
    
    Here are code snippets that use this library:
    
    {snippets_text}
    
    Provide a detailed compatibility assessment and suggestions for any necessary code changes.
    """
    
    # Call Claude 3.7 API (example implementation)
    try:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": claude_api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": "claude-3-7-sonnet-20250219",
            "system": "You are a quality assurance assistant. Analyze code snippets for compatibility with library versions and generates unit tests in seperate java file",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2000,
            "temperature": 0,
        }
        
        with open("log.text", "a") as log_file:
            log_file.write(f"Code Snippet List: {code_snippets}\n")
            log_file.write(f"Prompt: {prompt}\n")
            log_file.write("\n================================================\n================================================\n")
            log_file.write(f"Payload: {json.dumps(payload, indent=2)}\n")

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            data=json.dumps(payload),
            timeout=120
        )
        
        if response.status_code == 200:
            analysis = response.json()["content"][0]["text"]
            return {
                "status": "success",
                "compatibility_analysis": analysis
            }
        else:
            return {
                "status": "error", 
                "message": f"Failed to get response from Claude API: {response.text}"
            }
    
    except Exception as e:
        return {"status": "error", "message": f"Error communicating with Claude API: {str(e)}"}