import streamlit as st
import docx2txt
import tempfile
import requests
import pandas as pd
import os
import re
import json
import time
from dotenv import load_dotenv
from github import Github
import google.generativeai as genai
import PyPDF2

# Load environment variables from .env file
load_dotenv()

# Load credentials from environment variables
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Initialize session state
if 'tasks_data' not in st.session_state:
    st.session_state.tasks_data = []
if 'jira_created' not in st.session_state:
    st.session_state.jira_created = False
if 'branches_created' not in st.session_state:
    st.session_state.branches_created = False
if 'tests_created' not in st.session_state:
    st.session_state.tests_created = False
if 'selected_jira_key' not in st.session_state:
    st.session_state.selected_jira_key = JIRA_PROJECT_KEY
if 'selected_repo' not in st.session_state:
    st.session_state.selected_repo = GITHUB_REPO
if "view_and_manage" not in st.session_state:
    st.session_state["view_and_manage"] = False

# Your existing functions (keeping all of them)
def extract_text_from_docx(docx_path):
    return docx2txt.process(docx_path)

def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF file."""
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text()
        return text
    except Exception as e:
        st.error(f"Error extracting text from PDF: {e}")
        return None

def extract_text_from_txt(txt_path):
    """Extract text from a TXT file."""
    try:
        with open(txt_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        st.error(f"Error extracting text from TXT: {e}")
        return None

def extract_text_from_file(file_path, file_type):
    """Extract text from a file based on its type."""
    if file_type == 'docx':
        return extract_text_from_docx(file_path)
    elif file_type == 'pdf':
        return extract_text_from_pdf(file_path)
    elif file_type == 'txt':
        return extract_text_from_txt(file_path)
    else:
        st.error(f"Unsupported file type: {file_type}")
        return None

def prrse_tasks(text):
    lines = text.split('\n')
    return [line for line in lines if line.strip() != '']

def clean_text(text):
    return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")

def summarize_with_gemini(text):
    prompt = f"""
Document Task Extraction for Jira Issues

Please analyze the provided document (PDF, DOCX, or TXT) and extract all tasks that should be created as Jira issues. Organize them hierarchically as follows:

1. Identify main tasks/topics that will serve as "Epics" in Jira
2. Identify secondary tasks that will be "Tasks" under their respective Epics
3. Identify detailed work items that will be "Subtasks" under their respective Tasks
4. If a sub-subtask has its own subtasks, include them as sub-subtasks
5. the description should be taken from the document
6. keep the descriptions as short as possible but meaningful and concise which match in my document.
7. make sure to don't miss-out and infromation from the document
8. Do not include any sections related to Overview, Purpose, Scope, Tech stack suggestions, Time or hour estimates, Web design notes, Total days or effort summaries.
Format the output as JSON with the following structure:
{{
  "tasks": [
    {{
      "title": "Main Task 1",
      "description": "Take description of main task 1 from document",
      "subtasks": [
        {{
          "title": "Subtask 1.1",
          "description": "Take description of subtask 1.1 from document",
          "subtasks": [
            {{
              "title": "Sub-subtask 1.1.1",
              "description": "Take description of sub-subtask 1.1.1 from document"
            }}
          ]
        }}
      ]
    }}
  ]
}}
Important Guidelines:
- don't add None, Select, and choose between  in description of tasks
- if round brackets are used in the document then remove them from the description
- if there are smimilar sub-tasks put them in under one related task 
- if description is more than 200 characters then convert into subtasks
- use only text from the document to fill in the JSON structure
- Do not add any additional text or comments outside the JSON structure
- don't include any explanations or summaries
- don't use any extra text outside from the document
- Stricly Don't use \n or \t in the title and description
- Don't use any special characters in the title and description
Given the following document content, remove any sections related to:
- Overview Purpose Scope
- Tech stack suggestions
- Time or hour estimates
- Web design notes
- Total days or effort summaries
Document Content:
\"\"\"
{text}
\"\"\"
"""
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt,
        generation_config={"temperature": 0.1})
        raw_output = response.text.strip()

        match = re.search(r"\{[\s\S]*\}", raw_output)
        if match:
            return match.group(0)
        else:
            st.warning("No JSON block found in Gemini response.")
            return raw_output  # fallback
    except Exception as e:
        st.error(f"Gemini API error: {e}")
        return None

# Your existing display and utility functions
def count_tasks(tasks_data):
    """Count total number of tasks, subtasks, and sub-subtasks"""
    main_tasks = len(tasks_data)
    subtasks_count = 0
    sub_subtasks_count = 0
    
    for task in tasks_data:
        if "subtasks" in task:
            subtasks_count += len(task["subtasks"])
            
            for subtask in task["subtasks"]:
                if "subtasks" in subtask:
                    sub_subtasks_count += len(subtask["subtasks"])
                    
    return main_tasks, subtasks_count, sub_subtasks_count

def display_task_statistics(tasks_data):
    """Display task statistics in a neat layout"""
    main_tasks, subtasks_count, sub_subtasks_count = count_tasks(tasks_data)
    total_tasks = main_tasks + subtasks_count + sub_subtasks_count
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="stats-card">
            <div class="stats-number">{main_tasks}</div>
            <div class="stats-label">Main Tasks</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        st.markdown(f"""
        <div class="stats-card">
            <div class="stats-number">{subtasks_count}</div>
            <div class="stats-label">Subtasks</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col3:
        st.markdown(f"""
        <div class="stats-card">
            <div class="stats-number">{sub_subtasks_count}</div>
            <div class="stats-label">Sub-subtasks</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col4:
        st.markdown(f"""
        <div class="stats-card">
            <div class="stats-number">{total_tasks}</div>
            <div class="stats-label">Total Tasks</div>
        </div>
        """, unsafe_allow_html=True)

def display_sub_subtasks(sub_subtasks):
    """Display sub-subtasks with nice formatting"""
    for sub_subtask in sub_subtasks:
        st.markdown(f"""
        <div class="sub-subtask-container">
            <div class="sub-subtask-title">{sub_subtask["title"]}</div>
            <div class="sub-subtask-description">{sub_subtask.get("description", "")}</div>
        </div>
        """, unsafe_allow_html=True)

def display_subtasks(subtasks):
    """Display subtasks with nice formatting"""
    for subtask in subtasks:
        st.markdown(f"""
        <div class="subtask-container">
            <div class="subtask-title">{subtask["title"]}</div>
            <div class="subtask-description">{subtask.get("description", "")}</div>
        </div>
        """, unsafe_allow_html=True)
        
        if "subtasks" in subtask and subtask["subtasks"]:
            display_sub_subtasks(subtask["subtasks"])

def display_tasks(tasks_data):
    """Display tasks with nice formatting"""
    for task in tasks_data:
        with st.expander(f"**{task['title']}**", expanded=False):
            st.markdown(f"""
            <div class="task-card">
                <div class="task-title">{task["title"]}</div>
                <div class="task-description">{task.get("description", "")}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if "subtasks" in task and task["subtasks"]:
                display_subtasks(task["subtasks"])

def display_task_table(tasks_data):
    """Display tasks in a table format"""
    table_data = []
    
    for task_idx, task in enumerate(tasks_data):
        table_data.append({
            "Level": "Main Task",
            "ID": f"T{task_idx+1}",
            "Title": task["title"],
            "Description": task.get("description", "")
        })
        
        if "subtasks" in task:
            for subtask_idx, subtask in enumerate(task["subtasks"]):
                table_data.append({
                    "Level": "Subtask",
                    "ID": f"T{task_idx+1}.{subtask_idx+1}",
                    "Title": subtask["title"],
                    "Description": subtask.get("description", "")
                })
                
                if "subtasks" in subtask:
                    for sub_subtask_idx, sub_subtask in enumerate(subtask["subtasks"]):
                        table_data.append({
                            "Level": "Sub-subtask",
                            "ID": f"T{task_idx+1}.{subtask_idx+1}.{sub_subtask_idx+1}",
                            "Title": sub_subtask["title"],
                            "Description": sub_subtask.get("description", "")
                        })
    
    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

# NEW FUNCTIONALITY 1: TASK EDITING INTERFACE
def edit_tasks_interface(tasks_data):
    """Interactive task editing interface"""
    st.subheader("🛠️ Task Management")
    
    edit_tab, add_tab, delete_tab = st.tabs(["✏️ Edit", "➕ Add", "🗑️ Delete"])
    
    with edit_tab:
        st.write("### Edit Existing Tasks")
        
        # Create a flat list of all tasks for easy selection
        task_options = ["Select a task to edit..."]
        task_map = {}
        
        for i, task in enumerate(tasks_data):
            main_key = f"main_{i}"
            task_options.append(f"📋 Main Task {i+1}: {task['title']}")
            task_map[f"📋 Main Task {i+1}: {task['title']}"] = ("main", i, None, None)
            
            if "subtasks" in task:
                for j, subtask in enumerate(task["subtasks"]):
                    sub_key = f"sub_{i}_{j}"
                    task_options.append(f"    └─ 📝 Subtask {i+1}.{j+1}: {subtask['title']}")
                    task_map[f"    └─ 📝 Subtask {i+1}.{j+1}: {subtask['title']}"] = ("sub", i, j, None)
                    
                    if "subtasks" in subtask:
                        for k, sub_subtask in enumerate(subtask["subtasks"]):
                            task_options.append(f"        └─ 📌 Sub-subtask {i+1}.{j+1}.{k+1}: {sub_subtask['title']}")
                            task_map[f"        └─ 📌 Sub-subtask {i+1}.{j+1}.{k+1}: {sub_subtask['title']}"] = ("subsub", i, j, k)
        
        selected_task = st.selectbox("Select task to edit:", task_options)
        
        if selected_task != "Select a task to edit..." and selected_task in task_map:
            task_type, main_idx, sub_idx, subsub_idx = task_map[selected_task]
            
            if task_type == "main":
                current_task = tasks_data[main_idx]
                new_title = st.text_input("Title:", value=current_task["title"], key="edit_main_title")
                new_description = st.text_area("Description:", value=current_task.get("description", ""), key="edit_main_desc")
                
                if st.button("💾 Update Main Task", key="update_main"):
                    tasks_data[main_idx]["title"] = new_title
                    tasks_data[main_idx]["description"] = new_description
                    st.session_state.tasks_data = tasks_data
                    st.success("✅ Main task updated!")
                    time.sleep(1)
                    st.rerun()
                    
            elif task_type == "sub":
                current_task = tasks_data[main_idx]["subtasks"][sub_idx]
                new_title = st.text_input("Title:", value=current_task["title"], key="edit_sub_title")
                new_description = st.text_area("Description:", value=current_task.get("description", ""), key="edit_sub_desc")
                
                if st.button("💾 Update Subtask", key="update_sub"):
                    tasks_data[main_idx]["subtasks"][sub_idx]["title"] = new_title
                    tasks_data[main_idx]["subtasks"][sub_idx]["description"] = new_description
                    st.session_state.tasks_data = tasks_data
                    st.success("✅ Subtask updated!")
                    time.sleep(1)
                    st.rerun()
                    
            elif task_type == "subsub":
                current_task = tasks_data[main_idx]["subtasks"][sub_idx]["subtasks"][subsub_idx]
                new_title = st.text_input("Title:", value=current_task["title"], key="edit_subsub_title")
                new_description = st.text_area("Description:", value=current_task.get("description", ""), key="edit_subsub_desc")
                
                if st.button("💾 Update Sub-subtask", key="update_subsub"):
                    tasks_data[main_idx]["subtasks"][sub_idx]["subtasks"][subsub_idx]["title"] = new_title
                    tasks_data[main_idx]["subtasks"][sub_idx]["subtasks"][subsub_idx]["description"] = new_description
                    st.session_state.tasks_data = tasks_data
                    st.success("✅ Sub-subtask updated!")
                    time.sleep(1)
                    st.rerun()
    
    with add_tab:
        st.write("### Add New Tasks")
        
        add_type = st.radio("What would you like to add?", 
                           ["Main Task", "Subtask", "Sub-subtask"], key="add_type_radio")
        
        if add_type == "Main Task":
            new_title = st.text_input("New Main Task Title:", key="add_main_title")
            new_description = st.text_area("New Main Task Description:", key="add_main_desc")
            
            if st.button("➕ Add Main Task", key="add_main") and new_title:
                new_task = {
                    "title": new_title,
                    "description": new_description,
                    "subtasks": []
                }
                tasks_data.append(new_task)
                st.session_state.tasks_data = tasks_data
                st.success("✅ Main task added!")
                time.sleep(1)
                st.rerun()
        
        elif add_type == "Subtask":
            if tasks_data:
                main_task_options = [f"{i+1}: {task['title']}" for i, task in enumerate(tasks_data)]
                selected_main = st.selectbox("Select parent main task:", main_task_options, key="select_main_for_sub")
                
                if selected_main:
                    main_idx = int(selected_main.split(":")[0]) - 1
                    new_title = st.text_input("New Subtask Title:", key="add_sub_title")
                    new_description = st.text_area("New Subtask Description:", key="add_sub_desc")
                    
                    if st.button("➕ Add Subtask", key="add_sub") and new_title:
                        new_subtask = {
                            "title": new_title,
                            "description": new_description,
                            "subtasks": []
                        }
                        if "subtasks" not in tasks_data[main_idx]:
                            tasks_data[main_idx]["subtasks"] = []
                        tasks_data[main_idx]["subtasks"].append(new_subtask)
                        st.session_state.tasks_data = tasks_data
                        st.success("✅ Subtask added!")
                        time.sleep(1)
                        st.rerun()
            else:
                st.warning("⚠️ Please add a main task first.")
        
        elif add_type == "Sub-subtask":
            # Get available subtasks
            subtask_options = []
            subtask_map = {}
            
            for i, task in enumerate(tasks_data):
                if "subtasks" in task:
                    for j, subtask in enumerate(task["subtasks"]):
                        option_text = f"Task {i+1}.{j+1}: {subtask['title']}"
                        subtask_options.append(option_text)
                        subtask_map[option_text] = (i, j)
            
            if subtask_options:
                selected_subtask = st.selectbox("Select parent subtask:", subtask_options, key="select_sub_for_subsub")
                
                if selected_subtask:
                    main_idx, sub_idx = subtask_map[selected_subtask]
                    new_title = st.text_input("New Sub-subtask Title:", key="add_subsub_title")
                    new_description = st.text_area("New Sub-subtask Description:", key="add_subsub_desc")
                    
                    if st.button("➕ Add Sub-subtask", key="add_subsub") and new_title:
                        new_sub_subtask = {
                            "title": new_title,
                            "description": new_description
                        }
                        if "subtasks" not in tasks_data[main_idx]["subtasks"][sub_idx]:
                            tasks_data[main_idx]["subtasks"][sub_idx]["subtasks"] = []
                        tasks_data[main_idx]["subtasks"][sub_idx]["subtasks"].append(new_sub_subtask)
                        st.session_state.tasks_data = tasks_data
                        st.success("✅ Sub-subtask added!")
                        time.sleep(1)
                        st.rerun()
            else:
                st.warning("⚠️ Please add subtasks first.")
    
    with delete_tab:
        st.write("### Delete Tasks")
        st.warning("⚠️ Deletion cannot be undone!")
        
        # Reuse the same task selection logic
        task_options = ["Select a task to delete..."]
        task_map = {}
        
        for i, task in enumerate(tasks_data):
            task_options.append(f"📋 Main Task {i+1}: {task['title']}")
            task_map[f"📋 Main Task {i+1}: {task['title']}"] = ("main", i, None, None)
            
            if "subtasks" in task:
                for j, subtask in enumerate(task["subtasks"]):
                    task_options.append(f"    └─ 📝 Subtask {i+1}.{j+1}: {subtask['title']}")
                    task_map[f"    └─ 📝 Subtask {i+1}.{j+1}: {subtask['title']}"] = ("sub", i, j, None)
                    
                    if "subtasks" in subtask:
                        for k, sub_subtask in enumerate(subtask["subtasks"]):
                            task_options.append(f"        └─ 📌 Sub-subtask {i+1}.{j+1}.{k+1}: {sub_subtask['title']}")
                            task_map[f"        └─ 📌 Sub-subtask {i+1}.{j+1}.{k+1}: {sub_subtask['title']}"] = ("subsub", i, j, k)
        
        selected_to_delete = st.selectbox("Select task to delete:", task_options, key="delete_select")
        
        if selected_to_delete != "Select a task to delete..." and selected_to_delete in task_map:
            task_type, main_idx, sub_idx, subsub_idx = task_map[selected_to_delete]
            
            st.error(f"You are about to delete: **{selected_to_delete}**")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🗑️ Confirm Delete", type="secondary", key="confirm_delete"):
                    if task_type == "main":
                        deleted_task = tasks_data.pop(main_idx)
                        st.success(f"✅ Deleted main task: {deleted_task['title']}")
                    elif task_type == "sub":
                        deleted_task = tasks_data[main_idx]["subtasks"].pop(sub_idx)
                        st.success(f"✅ Deleted subtask: {deleted_task['title']}")
                    elif task_type == "subsub":
                        deleted_task = tasks_data[main_idx]["subtasks"][sub_idx]["subtasks"].pop(subsub_idx)
                        st.success(f"✅ Deleted sub-subtask: {deleted_task['title']}")
                    
                    st.session_state.tasks_data = tasks_data
                    time.sleep(1)
                    st.rerun()
            
            with col2:
                if st.button("❌ Cancel", key="cancel_delete"):
                    st.info("Delete operation cancelled.")
    
    return tasks_data

def save_edited_tasks(tasks_data):
    """Save edited tasks back to JSON file"""
    try:
        with open("geminisummary.json", "w", encoding="utf-8") as f:
            json.dump({"tasks": tasks_data}, f, indent=2, ensure_ascii=False)
        st.success("✅ Tasks saved successfully!")
        return True
    except Exception as e:
        st.error(f"❌ Failed to save tasks: {e}")
        return False

# NEW FUNCTIONALITY 2: PROJECT SELECTION INTERFACE
def get_jira_projects():
    """Fetch available Jira projects"""
    url = f"{JIRA_BASE_URL}/rest/api/3/project"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    try:
        response = requests.get(url, auth=auth)
        if response.status_code == 200:
            projects = response.json()
            return [(p["key"], p["name"]) for p in projects]
        else:
            st.error(f"Failed to fetch Jira projects: {response.status_code}")
    except Exception as e:
        st.error(f"Failed to fetch Jira projects: {e}")
    return []

def get_github_repos():
    """Fetch available GitHub repositories"""
    try:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        repos = user.get_repos()
        return [(repo.full_name, repo.name) for repo in repos]
    except Exception as e:
        st.error(f"Failed to fetch GitHub repos: {e}")
    return []
def get_jira_account_id():
    """Fetch the Atlassian accountId for the current Jira user."""
    url = f"{JIRA_BASE_URL}/rest/api/3/myself"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    try:
        response = requests.get(url, auth=auth)
        if response.status_code == 200:
            return response.json().get("accountId")
        else:
            st.error(f"Failed to fetch Jira accountId: {response.text}")
    except Exception as e:
        st.error(f"Error fetching Jira accountId: {e}")
    return None
def create_jira_project(project_key, project_name, project_type="software"):
    """Create a new Jira project"""
    url = f"{JIRA_BASE_URL}/rest/api/3/project"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)

    # Select correct template key based on project_type
    template_keys = {
        "software": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
        "business": "com.atlassian.jira-core-project-templates:jira-core-simplified-process-control",
        "service_desk": "com.atlassian.servicedesk:simplified-it-service-management"
    }
    projectTemplateKey = template_keys.get(project_type, template_keys["software"])

    # Get the accountId for the project lead
    lead_account_id = get_jira_account_id()
    if not lead_account_id:
        return False, "Could not fetch Jira accountId for project lead."

    payload = {
        "key": project_key,
        "name": project_name,
        "projectTypeKey": project_type,
        "projectTemplateKey": projectTemplateKey,
        "leadAccountId": lead_account_id
    }

    try:
        response = requests.post(url, json=payload, headers=headers, auth=auth)
        if response.status_code == 201:
            return True, response.json()
        else:
            # Check for duplicate project name/key error
            try:
                error_json = response.json()
                if (
                    'errors' in error_json and (
                        'projectName' in error_json['errors'] or 'projectKey' in error_json['errors']
                    )
                ):
                    # st.error("A project with that name or key already exists.")
                    return False, "A project with that name or key already exists please try with different name or key."
            except Exception:
                pass
            return False, f"Failed to create project: {response.text}"
    except Exception as e:
        return False, f"Error creating project: {str(e)}"

def create_github_repo(repo_name, description="", private=False):
    """Create a new GitHub repository"""
    try:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        repo = user.create_repo(
            name=repo_name,
            description=description,
            private=private,
            auto_init=True
        )
        return True, repo.full_name
    except Exception as e:
        # Check for duplicate repo name error
        try:
            if hasattr(e, 'data') and e.data:
                error_json = e.data
            else:
                error_json = json.loads(str(e).split(':', 1)[-1].strip())
            if (
                isinstance(error_json, dict) and
                error_json.get('errors') and
                any(err.get('message', '').lower().find('name already exists') != -1 for err in error_json['errors'])
            ):
                # st.error("A repository with that name already exists on this account.")
                return False, "A repository with that name already exists on this account please try with different name."
        except Exception:
            pass
        return False, f"Failed to create repository: {str(e)}"

def project_selection_interface():
    """Interface for selecting Jira project and GitHub repo"""
    st.subheader("🎯 Project Configuration")
    
    # Initialize variables with default values
    selected_jira_key = JIRA_PROJECT_KEY
    selected_repo = GITHUB_REPO
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("### 📋 Jira Project")
        
        jira_option = st.radio("Jira Project Option:", 
                              ["Use Default", "Select Existing", "Create New"], 
                              key="jira_option")
        
        if jira_option == "Use Default":
            st.info(f"Using default project: **{JIRA_PROJECT_KEY}**")
            
        elif jira_option == "Select Existing":
            with st.spinner("Fetching Jira projects..."):
                jira_projects = get_jira_projects()
                
            if jira_projects:
                project_options = [f"{key} - {name}" for key, name in jira_projects]
                selected_project = st.selectbox("Select Jira Project:", 
                                               [""] + project_options, 
                                               key="jira_project_select")
                
                if selected_project:
                    selected_jira_key = selected_project.split(" - ")[0]
                    st.success(f"Selected: **{selected_jira_key}**")
                else:
                    st.warning("No project selected, using default.")
            else:
                st.warning("No projects found or connection failed. Using default.")
                
        else:  # Create New
            st.write("### Create New Jira Project")
            new_project_key = st.text_input("Project Key:", placeholder="PROJ", key="new_jira_key")
            new_project_name = st.text_input("Project Name:", placeholder="My Project", key="new_jira_name")
            project_type = st.selectbox("Project Type:", ["software", "service_desk", "business"], key="jira_project_type")
            
            if st.button("Create Jira Project", key="project_create_jira_btn"):
                if new_project_key and new_project_name:
                    with st.spinner("Creating new Jira project..."):
                        success, result = create_jira_project(new_project_key, new_project_name, project_type)
                        if success:
                            st.success(f"✅ Project created successfully: {new_project_key}")
                            selected_jira_key = new_project_key
                        else:
                            st.error(f"❌ {result}")
                else:
                    st.warning("Please fill in all required fields.")
    
    with col2:
        st.write("### 🐙 GitHub Repository")
        
        github_option = st.radio("GitHub Repo Option:", 
                                 ["Use Default", "Select Existing", "Create New"], 
                                 key="github_option")
        
        if github_option == "Use Default":
            st.info(f"Using default repo: **{GITHUB_REPO}**")
            
        elif github_option == "Select Existing":
            with st.spinner("Fetching GitHub repositories..."):
                github_repos = get_github_repos()
                
            if github_repos:
                repo_options = [full_name for full_name, name in github_repos]
                selected_repo = st.selectbox("Select GitHub Repository:", 
                                           [""] + repo_options, 
                                           key="github_repo_select")
                
                if selected_repo:
                    st.success(f"Selected: **{selected_repo}**")
                else:
                    st.warning("No repository selected, using default.")
            else:
                st.warning("No repositories found or connection failed. Using default.")
                
        else:  # Create New
            st.write("### Create New GitHub Repository")
            new_repo_name = st.text_input("Repository Name:", placeholder="my-project", key="new_repo_name")
            new_repo_description = st.text_area("Description:", placeholder="Project description", key="new_repo_desc")
            is_private = st.checkbox("Private Repository", key="new_repo_private")
            
            if st.button("Create GitHub Repository", key="project_create_github_btn"):
                if new_repo_name:
                    with st.spinner("Creating new GitHub repository..."):
                        success, result = create_github_repo(new_repo_name, new_repo_description, is_private)
                        if success:
                            st.success(f"✅ Repository created successfully: {result}")
                            selected_repo = result
                        else:
                            st.error(f"❌ {result}")
                else:
                    st.warning("Please enter a repository name.")
    
    return selected_jira_key, selected_repo

# NEW FUNCTIONALITY 3: WORKFLOW VALIDATION
def validate_workflow_step(step_name, required_steps=[]):
    """Validate if workflow step can be executed"""
    if not required_steps:
        return True, ""
    
    missing_steps = []
    for req_step in required_steps:
        if not st.session_state.get(req_step, False):
            missing_steps.append(req_step.replace('_', ' ').title())
    
    if missing_steps:
        return False, f"Please complete: {', '.join(missing_steps)}"
    
    return True, ""

def reset_workflow_state():
    """Reset workflow state"""
    st.session_state.jira_created = False
    st.session_state.branches_created = False
    st.session_state.tests_created = False

# Your existing Jira and GitHub functions (keeping them all)
def get_valid_issue_types():
    url = f"{JIRA_BASE_URL}/rest/api/3/issuetype"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    response = requests.get(url, auth=auth)
    if response.status_code == 200:
        return [item["name"] for item in response.json()]
    return []

def create_jira_issue(summary, description, issue_type="Epic", parent_id=None, parent_type=None, project_key=None):
    if not project_key:
        project_key = st.session_state.selected_jira_key
    
    st.write(f"📝 Creating Jira issue: {summary}")

    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)

    valid_types = get_valid_issue_types()

    if not parent_id:
        issue_type_name = "Epic"
    elif parent_type == "Epic":
        issue_type_name = "Task"
    elif parent_type == "Task":
        issue_type_name = "Subtask"
    else:
        issue_type_name = "Task"

    if issue_type_name not in valid_types:
        st.warning(f"⚠️ Issue type '{issue_type_name}' is invalid. Falling back to 'Task'.")
        issue_type_name = "Task"

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description or ""}]
                    }
                ]
            },
            "issuetype": {"name": issue_type_name}
        }
    }

    if issue_type_name == "Subtask" and parent_id:
        payload["fields"]["parent"] = {"key": parent_id}
    elif issue_type_name == "Task" and parent_id:
        payload["fields"]["parent"] = {"key": parent_id}

    response = requests.post(url, json=payload, headers=headers, auth=auth)

    if response.status_code == 201:
        issue_key = response.json().get("key")
        st.success(f"✅ Created {issue_type_name}: {issue_key}")
        
        # Store the issue key in session state
        if 'jira_issue_keys' not in st.session_state:
            st.session_state.jira_issue_keys = {}
        st.session_state.jira_issue_keys[summary] = issue_key
        
        return issue_key, issue_type_name
    else:
        st.error(f"❌ Failed to create {issue_type_name}: {summary}")
        st.code(response.text)
        return None, None

def create_github_branch(branch_name, base="main", repo_name=None):
    if not repo_name:
        repo_name = st.session_state.selected_repo
    
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(repo_name)

    try:
        source = repo.get_branch(base)
    except Exception as e:
        st.error(f"⚠️ Could not find base branch '{base}'. Check if it exists in your GitHub repo.")
        st.stop()

    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=source.commit.sha)

def generate_test_case_prompt(ticket):
    """Generate a prompt for test case generation"""
    return f"""
You are a senior QA engineer. Based on the following task, write two detailed test cases including:
- A title
- Description
- Steps
- Expected Result
- Priority

Task:
Title: {ticket['summary']}
Description: {ticket['description']}
"""

def push_test_cases_to_branch(repo_name, branch_name, file_path, file_content):
    """Push test case files to their respective GitHub branches"""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(repo_name)
        
        # Get the branch
        branch = repo.get_branch(branch_name)
        
        # Create or update the file
        try:
            # Try to get the file first
            contents = repo.get_contents(file_path, ref=branch_name)
            # If file exists, update it
            repo.update_file(
                path=file_path,
                message=f"Update test cases for {branch_name}",
                content=file_content,
                sha=contents.sha,
                branch=branch_name
            )
        except Exception:
            # If file doesn't exist, create it
            repo.create_file(
                path=file_path,
                message=f"Add test cases for {branch_name}",
                content=file_content,
                branch=branch_name
            )
        
        return True, f"Successfully pushed test cases to {branch_name}"
    except Exception as e:
        return False, f"Failed to push test cases: {str(e)}"

def add_comment_to_jira_issue(issue_key, comment_content):
    """Add a comment to a Jira issue"""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment_content}]
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, auth=auth)
        if response.status_code == 201:
            return True, "Comment added successfully"
        else:
            return False, f"Failed to add comment: {response.text}"
    except Exception as e:
        return False, f"Error adding comment: {str(e)}"

def simulate_test_case_generation_ai(ticket, output_dir="test_cases", repo_name=None, branch_name=None):
    """Generate test cases using AI and optionally push to GitHub and Jira"""
    import google.generativeai as genai
    try:
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f"{ticket['key']}_test_cases.md")

        prompt = generate_test_case_prompt(ticket)

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        ai_output = response.text.strip()

        test_case_content = f"# Test Cases for {ticket['key']} - {ticket['summary']}\n\n{ai_output}"
        
        # Save locally
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(test_case_content)
            
        # If repo and branch are provided, push to GitHub
        if repo_name and branch_name:
            github_path = f"test_cases/{ticket['key']}_test_cases.md"
            success, message = push_test_cases_to_branch(repo_name, branch_name, github_path, test_case_content)
            if not success:
                st.warning(f"Warning: {message}")
            else:
                st.success(f"✅ Test cases pushed to {branch_name}")
        
        # Add test cases as a comment in Jira
        # Get the Jira issue key from the ticket
        jira_issue_key = ticket.get('jira_key')  # This should be set when creating the Jira issue
        if jira_issue_key:
            success, message = add_comment_to_jira_issue(jira_issue_key, test_case_content)
            if not success:
                st.warning(f"Warning: Failed to add test cases to Jira issue {jira_issue_key}: {message}")
            else:
                st.success(f"✅ Test cases added to Jira issue {jira_issue_key}")
                
    except Exception as e:
        st.error(f"❌ Error generating test cases for {ticket['key']}: {e}")
        fallback_path = os.path.join(output_dir, f"{ticket['key']}_error.log")
        with open(fallback_path, "w", encoding="utf-8") as f:
            f.write(f"# Critical error while processing {ticket['key']}\nError: {str(e)}")

def sanitize_branch_name(name):
    name = name.replace(" ", "_")
    name = re.sub(r'[^a-zA-Z0-9_\-\/]', '', name)
    return name

def walk_tasks_for_test_cases(tasks, parent_key="T", repo_name=None):
    for idx, task in enumerate(tasks):
        task_key = f"{parent_key}{idx+1}"
        # Get the Jira issue key from session state
        jira_key = st.session_state.jira_issue_keys.get(task.get("title", ""))
        ticket = {
            "key": task_key,
            "summary": task.get("title", ""),
            "description": task.get("description", ""),
            "jira_key": jira_key  # Add the Jira issue key to the ticket
        }
        
        # Generate branch name for this task
        branch_name = f"feature_{idx+1}_{sanitize_branch_name(task['title'])}".lower()
        
        # Generate and push test cases
        simulate_test_case_generation_ai(ticket, repo_name=repo_name, branch_name=branch_name)
        
        if "subtasks" in task and task["subtasks"]:
            for st_idx, stask in enumerate(task["subtasks"]):
                sub_task_key = f"{task_key}.{st_idx+1}"
                # Get the Jira issue key for the subtask
                sub_jira_key = st.session_state.jira_issue_keys.get(stask.get("title", ""))
                sub_ticket = {
                    "key": sub_task_key,
                    "summary": stask.get("title", ""),
                    "description": stask.get("description", ""),
                    "jira_key": sub_jira_key  # Add the Jira issue key to the subtask
                }
                
                # Generate branch name for this subtask
                sub_branch_name = f"feature_{idx+1}_{st_idx+1}_{sanitize_branch_name(stask['title'])}".lower()
                
                # Generate and push test cases
                simulate_test_case_generation_ai(sub_ticket, repo_name=repo_name, branch_name=sub_branch_name)
                
                if "subtasks" in stask and stask["subtasks"]:
                    for sst_idx, sstask in enumerate(stask["subtasks"]):
                        sub_sub_task_key = f"{sub_task_key}.{sst_idx+1}"
                        # Get the Jira issue key for the sub-subtask
                        sub_sub_jira_key = st.session_state.jira_issue_keys.get(sstask.get("title", ""))
                        sub_sub_ticket = {
                            "key": sub_sub_task_key,
                            "summary": sstask.get("title", ""),
                            "description": sstask.get("description", ""),
                            "jira_key": sub_sub_jira_key  # Add the Jira issue key to the sub-subtask
                        }
                        
                        # Generate branch name for this sub-subtask
                        sub_sub_branch_name = f"feature_{idx+1}_{st_idx+1}_{sst_idx+1}_{sanitize_branch_name(sstask['title'])}".lower()
                        
                        # Generate and push test cases
                        simulate_test_case_generation_ai(sub_sub_ticket, repo_name=repo_name, branch_name=sub_sub_branch_name)

# MAIN STREAMLIT UI
st.set_page_config(page_title="Jira Task Extractor App", layout="wide")

# Custom CSS for styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #CBD5E1;
    }
    
    .task-card {
        background-color: #F8FAFC;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
        border-left: 4px solid #1E3A8A;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    .task-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1E3A8A;
        margin-bottom: 5px;
    }
    
    .task-description {
        font-size: 0.9rem;
        color: #475569;
        margin-bottom: 10px;
    }
    
    .subtask-container {
        background-color: #F1F5F9;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 12px;
        border-left: 3px solid #3B82F6;
    }
    
    .subtask-title {
        font-size: 1rem;
        font-weight: 500;
        color: #2563EB;
        margin-bottom: 3px;
    }
    
    .subtask-description {
        font-size: 0.85rem;
        color: #64748B;
        margin-bottom: 8px;
    }
    
    .sub-subtask-container {
        background-color: #EFF6FF;
        border-radius: 6px;
        padding: 10px;
        margin-bottom: 8px;
        margin-left: 15px;
        border-left: 2px solid #60A5FA;
    }
    
    .sub-subtask-title {
        font-size: 0.9rem;
        font-weight: 500;
        color: #3B82F6;
        margin-bottom: 2px;
    }
    
    .sub-subtask-description {
        font-size: 0.8rem;
        color: #64748B;
    }
    
    .stats-card {
        background-color: #F0F9FF;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 15px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    
    .stats-number {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0369A1;
    }
    
    .stats-label {
        font-size: 0.9rem;
        color: #475569;
    }
    
    .workflow-step {
        background-color: #F8FAFC;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
        border-left: 4px solid #10B981;
    }
    
    .workflow-step.disabled {
        border-left-color: #9CA3AF;
        opacity: 0.6;
    }
    
    .workflow-step.completed {
        border-left-color: #059669;
        background-color: #ECFDF5;
    }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background-color: #F1F5F9;
        border-radius: 6px 6px 0px 0px;
        padding: 10px 16px;
        font-weight: 500;
    }
    
    .stTabs [aria-selected="true"] {
        background-color: #DBEAFE !important;
        color: #1E40AF !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📄📌 Jira Task Extractor App")

# Document Upload Section
uploaded_file = st.file_uploader("Upload a project document", type=["docx", "pdf", "txt"])

if uploaded_file is not None:
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as tmp_file:
        tmp_file.write(uploaded_file.read())
        temp_file_path = tmp_file.name

    st.success("File uploaded successfully!")

    text = extract_text_from_file(temp_file_path, file_extension)
    if text:
        cleaned_text = clean_text(text)
        tasks = prrse_tasks(text)

        st.subheader("Generating Summary")
        if st.button("Generate Response"):
            with st.spinner("Analyzing document and extracting tasks..."):
                summary = summarize_with_gemini(cleaned_text)
            
            st.write("### Summary:")
            if summary:
                with open("geminisummary.json", "w", encoding="utf-8") as f:
                    f.write(summary)
                st.subheader("📦 JSON Task Summary")
                st.text_area("JSON Response", summary, height=300)
                
                # Parse and store in session state
                try:
                    data = json.loads(summary)
                    if "tasks" in data:
                        st.session_state.tasks_data = data["tasks"]
                        reset_workflow_state()  # Reset workflow when new tasks are generated
                except json.JSONDecodeError:
                    st.error("Failed to parse JSON response")
            else:
                st.error("Failed to generate summary from the document.")

    os.unlink(temp_file_path)

# Task Management Section
use_saved = st.checkbox("🔁 View and manage extracted tasks", value=st.session_state["view_and_manage"], key="view_and_manage_checkbox")
st.session_state["view_and_manage"] = use_saved
if use_saved:
    try:
        # Try to load from file if session state is empty
        if not st.session_state.tasks_data:
            with open("geminisummary.json", "r", encoding="utf-8") as f:
                summary = f.read()
                data = json.loads(summary)
                if "tasks" in data:
                    st.session_state.tasks_data = data["tasks"]
        
        tasks_data = st.session_state.tasks_data
        
        if tasks_data:
            msg = st.success("Loaded tasks successfully!")
            time.sleep(1)
            msg.empty()
            
            # Display task statistics
            display_task_statistics(tasks_data)
            
            # Main task display tabs
            tab1, tab2 = st.tabs(["📋 Task Hierarchy", "📊 Task Table"])
            
            with tab1:
                display_tasks(tasks_data)
            with tab2:
                display_task_table(tasks_data)

            # ENHANCED TASK MANAGEMENT SECTION
            st.markdown("---")
            
            # Task editing interface
            edit_tasks = st.checkbox("🛠️ Edit/Add/Delete Tasks")
            if edit_tasks:
                st.session_state.tasks_data = edit_tasks_interface(st.session_state.tasks_data)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("💾 Save Changes", type="primary"):
                        if save_edited_tasks(st.session_state.tasks_data):
                            st.rerun()
                
                with col2:
                    if st.button("🔄 Reset to Saved", type="secondary"):
                        with open("geminisummary.json", "r", encoding="utf-8") as f:
                            data = json.loads(f.read())
                            st.session_state.tasks_data = data["tasks"]
                        st.success("Reset to last saved version!")
                        st.rerun()

            # Task confirmation and workflow
            st.markdown("---")
            st.subheader("🚀 Development Workflow")
            
            # Workflow progress indicator
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.session_state.jira_created:
                    st.success("✅ Jira Issues Created")
                else:
                    st.info("⏳ Jira Issues Pending")
            
            with col2:
                if st.session_state.branches_created:
                    st.success("✅ GitHub Branches Created")
                else:
                    st.info("⏳ GitHub Branches Pending")
            
            with col3:
                if st.session_state.tests_created:
                    st.success("✅ Test Cases Generated")
                else:
                    st.info("⏳ Test Cases Pending")

            # Task confirmation
            task_confirmed = st.checkbox("✅ Confirm tasks are ready for development")
            
            if task_confirmed:
                st.success("Tasks confirmed! Ready to proceed with project setup.")
                
                # Project selection interface
                selected_jira_key, selected_repo = project_selection_interface()
                
                # Store selections in session state
                st.session_state.selected_jira_key = selected_jira_key
                st.session_state.selected_repo = selected_repo
                
                st.markdown("---")
                st.subheader("⚡ Execute Workflow")
                
                # Workflow execution buttons with validation
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    can_create_jira, jira_msg = validate_workflow_step("jira_creation")
                    
                    if st.button("📋 Create Jira Issues", 
                               type="primary",
                               disabled=not can_create_jira,
                               key="workflow_create_jira_btn"):
                        
                        try:
                            with st.spinner("Creating Jira issues..."):
                                progress_bar = st.progress(0)
                                total_tasks = len(tasks_data)
                                
                                for idx, t in enumerate(tasks_data):
                                    epic_key, epic_type = create_jira_issue(
                                        t["title"], 
                                        t.get("description", ""),
                                        project_key=selected_jira_key
                                    )
                                    
                                    if epic_key:
                                        for stask in t.get("subtasks", []):
                                            task_key, task_type = create_jira_issue(
                                                stask["title"], 
                                                stask.get("description", ""),
                                                parent_id=epic_key, 
                                                parent_type=epic_type,
                                                project_key=selected_jira_key
                                            )
                                            
                                            if task_key:
                                                for sstask in stask.get("subtasks", []):
                                                    create_jira_issue(
                                                        sstask["title"], 
                                                        sstask.get("description", ""),
                                                        parent_id=task_key, 
                                                        parent_type=task_type,
                                                        project_key=selected_jira_key
                                                    )
                                    
                                    progress_bar.progress((idx + 1) / total_tasks)
                                
                                progress_bar.empty()
                            
                            st.success("🎉 All Jira issues created successfully!")
                            st.session_state.jira_created = True
                            time.sleep(1)
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Jira issue creation failed: {e}")
                    
                    if not can_create_jira:
                        st.warning(jira_msg)
                
                with col2:
                    can_create_branches, branch_msg = validate_workflow_step("branch_creation", ["jira_created"])
                    
                    if st.button("🌿 Create GitHub Branches", 
                               type="primary" if can_create_branches else "secondary",
                               disabled=not can_create_branches,
                               key="workflow_create_branches_btn"):
                        
                        try:
                            with st.spinner("Creating GitHub branches..."):
                                progress_bar = st.progress(0)
                                total_operations = 0
                                
                                # Count total operations
                                for t in tasks_data:
                                    total_operations += 1
                                    total_operations += len(t.get("subtasks", []))
                                    for stask in t.get("subtasks", []):
                                        total_operations += len(stask.get("subtasks", []))
                                
                                current_op = 0
                                
                                for t_idx, t in enumerate(tasks_data):
                                    branch_name = f"feature_{t_idx+1}_{sanitize_branch_name(t['title'])}".lower()
                                    create_github_branch(branch_name, repo_name=selected_repo)
                                    current_op += 1
                                    progress_bar.progress(current_op / total_operations)
                                    
                                    for st_idx, stask in enumerate(t.get("subtasks", [])):
                                        sub_branch_name = f"feature_{t_idx+1}_{st_idx+1}_{sanitize_branch_name(stask['title'])}".lower()
                                        create_github_branch(sub_branch_name, repo_name=selected_repo)
                                        current_op += 1
                                        progress_bar.progress(current_op / total_operations)
                                        
                                        for sst_idx, sstask in enumerate(stask.get("subtasks", [])):
                                            sub_sub_branch_name = f"feature_{t_idx+1}_{st_idx+1}_{sst_idx+1}_{sanitize_branch_name(sstask['title'])}".lower()
                                            create_github_branch(sub_sub_branch_name, repo_name=selected_repo)
                                            current_op += 1
                                            progress_bar.progress(current_op / total_operations)
                                
                                progress_bar.empty()
                            
                            st.success("🌿 All GitHub branches created successfully!")
                            st.session_state.branches_created = True
                            time.sleep(1)
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Branch creation failed: {e}")
                    
                    if not can_create_branches:
                        st.warning(branch_msg)
                
                with col3:
                    can_create_tests, test_msg = validate_workflow_step("test_creation", ["jira_created", "branches_created"])
                    
                    if st.button("🧪 Generate & Push Test Cases", 
                               type="primary" if can_create_tests else "secondary",
                               disabled=not can_create_tests,
                               key="workflow_create_tests_btn"):
                        
                        try:
                            with st.spinner("Generating and pushing test cases..."):
                                walk_tasks_for_test_cases(tasks_data, repo_name=selected_repo)
                            
                            st.success("🧪 Test cases generated and pushed successfully!")
                            st.session_state.tests_created = True
                            time.sleep(1)
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Test case generation and pushing failed: {e}")
                    
                    if not can_create_tests:
                        st.warning(test_msg)
                
                # Workflow completion status
                if all([
                    st.session_state.jira_created,
                    st.session_state.branches_created,
                    st.session_state.tests_created
                ]):
                    st.balloons()
                    st.success("🎉 Complete workflow executed successfully!")
                    st.info("Your document has been transformed into a complete development workflow!")
                    
                    # Option to reset workflow
                    if st.button("🔄 Start New Workflow", type="secondary"):
                        st.session_state["view_and_manage"] = False  # Custom session var to control checkbox
                        reset_workflow_state()
                        st.rerun()
        
        else:
            st.warning("No tasks found. Please upload a document and generate tasks first.")
    
    except FileNotFoundError:
        st.error("JSON file not found. Please upload a document and generate tasks first.")
    except json.JSONDecodeError:
        st.error("Could not parse JSON from file.")
    except Exception as e:
        st.error(f"An error occurred: {e}")

