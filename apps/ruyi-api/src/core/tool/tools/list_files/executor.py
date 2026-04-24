"""ListFiles 工具的执行逻辑与输出格式化。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from core.tool.types import ToolResult
import os

# 设置最大文件列表长度
MAX_FILE_LIST_LENGTH=1000

@dataclass
class ListFilesData:
    folder_path:str
    files:list[dict[str,Any]]

async def list_files_handler(args:dict[str,Any])-> ToolResult:
    """列出指定文件夹下的所有文件和子文件夹"""
    folder_path:str=args.get("folder_path","")
    # 参数验证
    if not folder_path:
        return ToolResult.fail("folder_path is required")
    # 路径规范化
    folder_path=os.path.expanduser(folder_path)
    if not os.path.isabs(folder_path):
        folder_path=os.path.abspath(folder_path)
    
    if not os.path.isdir(folder_path):
        return ToolResult.fail(f"Folder not found: {folder_path}")
    
    # 读取文件夹下面的文件夹和文件 -列表最大长度限制
    files=[]
    try:
        folder=Path(folder_path)
        for item in folder.iterdir():
            if len(files)>=MAX_FILE_LIST_LENGTH:
                break
            files.append({
                "path":str(item),
                "type":"file" if item.is_file() else "directory",
            })
    except PermissionError:
        return ToolResult.fail(f"Permission denied: {folder_path}")
    except Exception as e:
        return ToolResult.fail(f"Error listing files: {e}")
    
    return ToolResult.ok(ListFilesData(
        folder_path=folder_path,
        files=files,
    ))
    
def render_list_files_result(result:ToolResult)->str:
    if not result.success:
        return f"Error listing files: {result.error}"
    
    data:ListFilesData=result.data
    output="Folder: {data.folder_path}\n"
    output+="Files:\n"
    for file in data.files:
        output+=f"- {file['path']} ({file['type']})\n"
    return output