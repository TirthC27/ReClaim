import os
import ast
import json

def generate_tree(dir_path, exclude_dirs, exclude_exts, prefix=""):
    tree_str = ""
    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return ""
    
    entries = [e for e in entries if e not in exclude_dirs and not any(e.endswith(ext) for ext in exclude_exts)]
    
    for i, entry in enumerate(entries):
        is_last = (i == len(entries) - 1)
        path = os.path.join(dir_path, entry)
        connector = "└── " if is_last else "├── "
        tree_str += f"{prefix}{connector}{entry}\n"
        
        if os.path.isdir(path):
            extension = "    " if is_last else "│   "
            tree_str += generate_tree(path, exclude_dirs, exclude_exts, prefix + extension)
            
    return tree_str

def get_file_content(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def extract_routes(filepath):
    content = get_file_content(filepath)
    if not content: return ""
    
    routes = []
    try:
        tree = ast.parse(content)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    # Look for @router.post, @router.get, etc.
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                        if hasattr(decorator.func.value, 'id') and decorator.func.value.id == 'router':
                            method = decorator.func.attr
                            path = ""
                            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                                path = decorator.args[0].value
                            
                            args = [arg.arg for arg in node.args.args]
                            signature = f"def {node.name}({', '.join(args)}):"
                            routes.append(f"@{decorator.func.value.id}.{method}(\"{path}\")\n{signature}")
    except Exception as e:
        pass
    
    return "\n\n".join(routes)

def main():
    root_dir = "."
    exclude_dirs = {"node_modules", ".git", "__pycache__", "venv", "dist", "build", ".pytest_cache", ".idea", ".vscode"}
    exclude_exts = {".pyc", ".env", ".sqlite"}
    
    out = []
    out.append("# PROJECT_CONTEXT Snapshot\n")
    
    # 1. Directory Tree
    out.append("## 1. Directory Tree\n```")
    out.append(generate_tree(root_dir, exclude_dirs, exclude_exts))
    out.append("```\n")
    
    # 2. Schema / Migration Files
    out.append("## 2. Schema / Migration Files\n")
    migrations_dir = os.path.join("app", "migrations")
    if os.path.exists(migrations_dir):
        for f in sorted(os.listdir(migrations_dir)):
            if f.endswith(".sql"):
                out.append(f"### {f}\n```sql\n{get_file_content(os.path.join(migrations_dir, f))}\n```\n")
                
    # 3. Pydantic Models
    out.append("## 3. Pydantic Models (Schemas)\n")
    schemas_path = os.path.join("app", "models", "schemas.py")
    out.append(f"### schemas.py\n```python\n{get_file_content(schemas_path)}\n```\n")
    
    # 4. API Routes
    out.append("## 4. API Routes\n")
    routers_dir = os.path.join("app", "routers")
    if os.path.exists(routers_dir):
        for f in sorted(os.listdir(routers_dir)):
            if f.endswith(".py") and f != "__init__.py":
                routes = extract_routes(os.path.join(routers_dir, f))
                if routes:
                    out.append(f"### {f}\n```python\n{routes}\n```\n")
                    
    # 5. .env.example
    out.append("## 5. .env.example\n```bash\n")
    out.append(get_file_content(".env.example"))
    out.append("\n```\n")
    
    # 6. requirements.txt / package.json
    out.append("## 6. Dependencies\n")
    out.append("### requirements.txt\n```text\n")
    out.append(get_file_content("requirements.txt"))
    out.append("\n```\n")
    
    out.append("### merchant-dashboard/package.json\n```json\n")
    out.append(get_file_content(os.path.join("merchant-dashboard", "package.json")))
    out.append("\n```\n")
    
    # 7. Implementation Note
    out.append("## 7. Implementation Status\n")
    out.append("""
### What's Implemented:
- Prompt 1: Database schema (tables for merchants, demand pools, offers, etc.) and basic FastAPI setup.
- Prompt 2: Merchant onboarding API, Shopify vendor syncing, document uploads, and product mapping logic.
- Prompt 3: Shopify webhooks (checkout-create and order-create) integration, demand aggregation (bundling abandoned carts), and the APScheduler background job for checking abandonment timeout.
- Prompt 4: Multi-Agent LLM Offer Engine (Strategy + Composer), PGVector RAG integration, and Section 9A.2 fair round-robin allocation logic for resolving tied offers.
- Prompt 5: Razorpay payment links generation, idempotent webhook handling for `payment_link.paid`, Shopify order auto-creation post payment, and a full React Router frontend (Dashboard, Competition View, Marketplace, Allocation transparency, Payment Success).

### What's Stubbed/Incomplete:
- All 5 prompts have been fully implemented according to the specifications. 
- While production deployment details (e.g. Supabase Edge Functions instead of APScheduler, or a true Celery queue) are stubbed out in favor of in-process task queues for hackathon scope, the core logic as requested is fully intact and functional.
- The only manual steps remaining are setting the external API keys (Shopify, Razorpay, OpenRouter, Supabase) and registering the Shopify webhook in the store admin.
""")

    with open("PROJECT_CONTEXT.md", "w", encoding="utf-8") as f:
        f.write("".join(out))

if __name__ == "__main__":
    main()
