import aiohttp
import asyncio
import json
import os
import time
import logging

logger = logging.getLogger("comfycloud")

class ComfyCloudClient:
    """Async client for ComfyCloud API."""

    def __init__(self, api_key: str, base_url: str = "https://api.comfy.org"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"X-API-Key": self.api_key}
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def upload_image(self, image_path: str) -> str:
        """Upload image to ComfyCloud. Returns the filename reference for workflow JSON."""
        session = await self._get_session()
        with open(image_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("image", f, filename=os.path.basename(image_path))
            async with session.post(f"{self.base_url}/api/upload/image", data=data) as resp:
                resp.raise_for_status()
                result = await resp.json()
                filename = result.get("name", result.get("filename", ""))
                subfolder = result.get("subfolder", "")
                if subfolder:
                    return f"{subfolder}/{filename}"
                return filename

    async def submit_workflow(self, workflow_json: dict) -> str:
        """Submit workflow for execution. Returns prompt_id."""
        session = await self._get_session()
        payload = {"prompt": workflow_json}
        async with session.post(f"{self.base_url}/api/prompt", json=payload) as resp:
            resp.raise_for_status()
            result = await resp.json()
            prompt_id = result.get("prompt_id", "")
            logger.info(f"Submitted workflow, prompt_id={prompt_id}")
            return prompt_id

    async def poll_status(self, prompt_id: str, timeout: int = 600, interval: int = 5) -> dict:
        """Poll /api/history/{prompt_id} until complete. Returns the output data."""
        session = await self._get_session()
        start = time.time()
        while time.time() - start < timeout:
            async with session.get(f"{self.base_url}/api/history/{prompt_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if prompt_id in data:
                        entry = data[prompt_id]
                        status = entry.get("status", {})
                        if status.get("completed", False) or status.get("status_str") == "success":
                            return entry.get("outputs", {})
                        if status.get("status_str") in ("error", "failed"):
                            raise RuntimeError(f"Workflow failed: {status}")
            await asyncio.sleep(interval)
        raise TimeoutError(f"Workflow {prompt_id} timed out after {timeout}s")

    async def download_output(self, filename: str, output_dir: str, filetype: str = "output") -> str:
        """Download output file. Returns local file path."""
        session = await self._get_session()
        url = f"{self.base_url}/api/view"
        params = {"filename": filename, "type": filetype}
        async with session.get(url, params=params, allow_redirects=True) as resp:
            resp.raise_for_status()
            local_path = os.path.join(output_dir, os.path.basename(filename))
            with open(local_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
            logger.info(f"Downloaded {filename} -> {local_path}")
            return local_path

    async def run_workflow(self, workflow_json: dict, output_dir: str, timeout: int = 600) -> list:
        """Full lifecycle: submit, poll, download all outputs. Returns list of local paths."""
        prompt_id = await self.submit_workflow(workflow_json)
        outputs = await self.poll_status(prompt_id, timeout=timeout)

        downloaded = []
        for node_id, node_output in outputs.items():
            # Images
            for img in node_output.get("images", []):
                fname = img.get("filename", "")
                if fname:
                    path = await self.download_output(fname, output_dir)
                    downloaded.append(path)
            # Videos (gifs, mp4s, etc.)
            for vid in node_output.get("videos", []) + node_output.get("gifs", []):
                fname = vid.get("filename", "")
                if fname:
                    path = await self.download_output(fname, output_dir)
                    downloaded.append(path)

        return downloaded
