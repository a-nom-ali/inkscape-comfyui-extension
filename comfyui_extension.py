#!/usr/bin/env python3
"""
This module defines an Inkscape extension for integrating with the ComfyUI API,
allowing users to generate AI-powered images and insert them into SVG designs.

Classes:
    ComfyUIWebSocketAPI: Handles API communication with the ComfyUI server.
    ComfyUIExtension: Main extension logic for Inkscape.

Dependencies:
    - PIL (Pillow)
    - requests
    - lxml
    - inkex
"""

import os
import json
import base64
import subprocess
import sys
import time
import tempfile  # For temporary directory
import shutil  # For cleaning up
from urllib import request
import urllib.parse
import random
import uuid
import inkex
from inkex.command import inkscape  # Import inkscape command function
from lxml import etree
import requests
from PIL import Image


def retry_request(url, data=None, headers=None, max_retries=5, backoff_factor=0.5):
    """
    Sends a request to the server with retry logic for handling failures.

    Args:
        url (str): URL for the request.
        data (bytes): Data to send with the request.
        headers (dict): HTTP headers.
        max_retries (int): Maximum number of retries.
        backoff_factor (float): Delay multiplier for exponential backoff.

    Returns:
        bytes: Response data from the server.
    """
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data) if headers is None \
                else urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req) as response:
                return response.read()
        except urllib.error.URLError as error:
            if attempt < max_retries - 1:
                sleep_time = backoff_factor * (2 ** attempt)
                time.sleep(sleep_time)
            else:
                inkex.errormsg(f"Max retries reached for URL: {url}")
                raise TimeoutError(f"Request timed out after {max_retries} attempts: {error}")

    return None


class ComfyUIWebSocketAPI:
    """
    Handles communication with the ComfyUI server via WebSocket API.

    Attributes:
        server_address (str): Address of the ComfyUI server.
        client_id (str): Unique identifier for the client.
    """

    def __init__(self, server_address="127.0.0.1:8188"):
        """
        Initializes the ComfyUIWebSocketAPI with a server address and client ID.

        Args:
            server_address (str): Address of the ComfyUI server.
        """
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())

    def queue_prompt(self, prompt):
        """
        Queues a prompt on the ComfyUI server.

        Args:
            prompt (dict): Prompt data.

        Returns:
            dict: JSON response containing the prompt ID.
        """
        prompt_json = {"prompt": prompt, "client_id": self.client_id}
        data = json.dumps(prompt_json).encode('utf-8')
        req = urllib.request.Request(f"http://{self.server_address}/prompt", data=data)
        return json.loads(urllib.request.urlopen(req).read())

    def get_image(self, filename, subfolder, folder_type):
        """
        Retrieves an image from the ComfyUI server.

        Args:
            filename (str): Name of the file to retrieve.
            subfolder (str): Subfolder containing the file.
            folder_type (str): Folder type.

        Returns:
            bytes: Image data.
        """
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        with urllib.request.urlopen(f"http://{self.server_address}/view?{url_values}") as response:
            return response.read()

    def get_history(self, prompt_id):
        """
        Retrieves the history of a prompt from the server.

        Args:
            prompt_id (str): ID of the prompt.

        Returns:
            dict: History data for the prompt.
        """
        url = f"http://{self.server_address}/history/{prompt_id}"
        response = retry_request(url)
        # inkex.utils.debug(response)
        response_data = json.loads(response)

        return response_data

    def upload_file(self, file, subfolder="", overwrite=False):
        """
        Uploads a file to the ComfyUI server.

        Args:
            file (file-like object): File to upload.
            subfolder (str): Subfolder to upload the file to.
            overwrite (bool): Whether to overwrite existing files.

        Returns:
            str: Path to the uploaded file.
        """
        path = None

        # Wrap file in formdata so it includes filename
        body = {"image": file}
        data = {}

        if overwrite:
            data["overwrite"] = "true"

        if subfolder:
            data["subfolder"] = subfolder

        try:
            resp = requests.post(
                f"http://{self.server_address}/upload/image",
                files=body,
                data=data,
                timeout=300)
            resp.raise_for_status()  # Raises HTTPError for bad responses
        except requests.exceptions.RequestException as error:
            raise requests.exceptions.RequestException(f"Upload request failed: {error}")

        if resp.status_code == 200:
            data = resp.json()

            if "name" not in data:
                raise ValueError("Server response is missing the file name.")

            # Add the file to the dropdown list and update the widget value
            path = data["name"]

            if "subfolder" in data and data["subfolder"] != "":
                path = f"{data['subfolder']}/{path}"
        else:
            inkex.utils.debug(f"{resp.status_code} - {resp.reason}")

        return path

    def load_image(self, filepath):
        """
        Uploads an image file to the server.

        Args:
            filepath (str): Path to the image file.

        Returns:
            str: Server path to the uploaded image.
        """
        with open(filepath, "rb") as file:
            image = self.upload_file(file, "", True)
        return image

    def load_workflow(self, filepath):
        """
        Loads a workflow JSON file.

        Args:
            filepath (str): Path to the workflow JSON file.

        Returns:
            dict: Parsed workflow JSON data.
        """
        with open(filepath, "r", encoding="utf-8") as file:
            workflow_data = file.read()

        return json.loads(workflow_data)


class ComfyUIExtension(inkex.EffectExtension):
    """
    Inkscape extension for integrating with ComfyUI to generate and insert images.

    Methods:
        add_arguments: Adds user-configurable parameters to the extension.
        effect: Main execution logic for the extension.
    """

    inkscape_ns = "http://www.inkscape.org/namespaces/inkscape"

    def __init__(self):
        self.tempdir = None
        self.comfy = None
        self.content_width = 0
        self.content_height = 0
        self.exported_width = 0
        self.exported_height = 0
        self.longest_side = 0
        self.offset_x = 0
        self.offset_y = 0

        inkex.EffectExtension.__init__(self)

    def add_arguments(self, pars):
        """
        Adds arguments to the Inkscape extension's user interface.

        Args:
            pars (inkex.ArgumentParser): The argument parser to define user options.

        Parameters:
            --tab: Tracks the selected UI tab.
            --workflow_select: Selects the workflow.
            --positive_prompt: User-provided text for the positive prompt in the workflow.
            --negative_prompt: User-provided text for the negative prompt in the workflow.
            --cfg_scale: CFG scale (guidance strength) for the image generation.
            --denoise: Denoising level for the image generation.
            --seed: Random seed for reproducibility.
            --steps: Number of sampling steps for image generation.

            --basic_positive_id: Identifier for the positive prompt node in the Basic workflow JSON.
            --basic_negative_id: Identifier for the negative prompt node in the Basic workflow JSON.
            --basic_ksampler_id: Identifier for the sampler node in the Basic workflow JSON.

            --img2img_positive_id: Identifier for the positive prompt node in the Image To Image workflow JSON.
            --img2img_negative_id: Identifier for the negative prompt node in the Image To Image workflow JSON.
            --img2img_image_input_id: Identifier for the image input node in the Image To Image workflow JSON.
            --img2img_ksampler_id: Identifier for the sampler node in the Image To Image workflow JSON.

            --masked_positive_id: Identifier for the positive prompt node in the Inpainting/Masked workflow JSON.
            --masked_negative_id: Identifier for the negative prompt node in the Inpainting/Masked workflow JSON.
            --masked_image_input_id: Identifier for the image input node in the Inpainting/Masked workflow JSON.
            --masked_mask_input_id: Identifier for the mask input node in the Inpainting/Masked workflow JSON.
            --masked_ksampler_id: Identifier for the sampler node in the Inpainting/Masked workflow JSON.

            --pose_positive_id: Identifier for the positive prompt node in the Pose workflow JSON.
            --pose_negative_id: Identifier for the negative prompt node in the Pose workflow JSON.
            --pose_image_input_id: Identifier for the image input node in the Pose workflow JSON.
            --pose_input_id: Identifier for the pose input node in the Pose workflow JSON.
            --pose_ksampler_id: Identifier for the sampler node in the Pose workflow JSON.

            --workflow_json_path: File path to the workflow JSON.
            --api_url: Base URL of the ComfyUI server API.
        """
        pars.add_argument(
            "--tab",
            default=self.tab_select,
            help="The selected UI-tab when OK was pressed",
        )
        pars.add_argument(
            "--ids_tab",
            default=self.ids_tab_select,
            help="The selected UI-tab when OK was pressed",
        )

        pars.add_argument("--workflow_select", type=str, help="Select Workflow")
        pars.add_argument("--positive_prompt", type=str, help="Positive Prompt")
        pars.add_argument("--negative_prompt", type=str, help="Negative Prompt")
        pars.add_argument("--cfg_scale", type=float, default=7.0, help="CFG Scale")
        pars.add_argument("--denoise", type=float, default=0.75, help="Denoise")
        pars.add_argument("--seed", type=int, default=0, help="Seed")
        pars.add_argument("--steps", type=int, default=20, help="Steps")

        pars.add_argument("--basic_positive_id", type=int, default=30, help="Positive Prompt ID")
        pars.add_argument("--basic_negative_id", type=int, default=33, help="Negative Prompt ID")
        pars.add_argument("--basic_ksampler_id", type=int, default=3, help="KSampler ID")

        pars.add_argument("--img2img_positive_id", type=int, default=16, help="Positive Prompt ID")
        pars.add_argument("--img2img_negative_id", type=int, default=19, help="Negative Prompt ID")
        pars.add_argument("--img2img_image_input_id", type=int, default=38, help="Image Input ID")
        pars.add_argument("--img2img_ksampler_id", type=int, default=36, help="KSampler ID")

        pars.add_argument("--masked_positive_id", type=int, default=16, help="Positive Prompt ID")
        pars.add_argument("--masked_negative_id", type=int, default=19, help="Negative Prompt ID")
        pars.add_argument("--masked_image_input_id", type=int, default=38, help="Image Input ID")
        pars.add_argument("--masked_mask_input_id", type=int, default=0, help="Mask Input ID")
        pars.add_argument("--masked_ksampler_id", type=int, default=36, help="KSampler ID")

        pars.add_argument("--pose_positive_id", type=int, default=16, help="Positive Prompt ID")
        pars.add_argument("--pose_negative_id", type=int, default=19, help="Negative Prompt ID")
        pars.add_argument("--pose_image_input_id", type=int, default=38, help="Image Input ID")
        pars.add_argument("--pose_input_id", type=int, default=0, help="Pose Input ID")
        pars.add_argument("--pose_ksampler_id", type=int, default=36, help="KSampler ID")

        pars.add_argument("--basic_workflow_json_path", type=str, help="Basic Workflow JSON Path")
        pars.add_argument("--img2img_workflow_json_path", type=str, help="Image To Image Workflow JSON Path")
        pars.add_argument("--masked_workflow_json_path", type=str, help="Inpainting/Masked Workflow JSON Path")
        pars.add_argument("--pose_workflow_json_path", type=str, help="Pose Workflow JSON Path")
        pars.add_argument("--api_url", type=str, default="127.0.0.1:8188", help="API URL")

    def tab_select(self, _):
        """
        Determines which tab in the user interface should be selected
        based on the presence of key options.

        Args:
            _: Placeholder for unused argument, required by the method signature.

        Returns:
            str: The name of the selected tab ('controls' or 'comfy').
        """
        return "controls" if self.options.api_url and self.options.basic_workflow_json_path else "comfy"

    def ids_tab_select(self, _):
        """
        Determines which IDs tab in the user interface should be selected
        based on the presence of key options.

        Args:
            _: Placeholder for unused argument, required by the method signature.

        Returns:
            str: The name of the selected tab ('controls' or 'comfy').
        """
        return "img2img"

    def effect(self):
        """
        Main execution logic for the extension. Validates inputs, processes
        selected SVG elements, generates AI-powered images using ComfyUI,
        and inserts the results back into the SVG document.
        """
        self.setup()  # Set up namespaces and API client
        self.validate_parameters()  # Ensure required inputs are present

        # Create a temporary directory for intermediate files
        self.tempdir = tempfile.mkdtemp()

        try:
            # Select the workflow path
            workflow_json_path = self.get_workflow_path()

            # Load the workflow JSON from the specified file
            workflow_json = self.load_workflow_json(workflow_json_path)

            # Populate workflow with user inputs and prepared image
            workflow_json = self.populate_workflow(workflow_json)

            # Generate the result image using the ComfyUI API
            result_image_path = self.generate_result_image(workflow_json)

            # Insert the generated result image back into the SVG
            self.insert_result_image(result_image_path, workflow_json)

        finally:
            # Clean up the temporary directory after processing
            shutil.rmtree(self.tempdir)

    def setup(self):
        """
        Sets up required namespaces and initializes the ComfyUI API client.
        """
        # Define Inkscape namespace
        etree.register_namespace("inkscape", self.inkscape_ns)
        self.comfy = ComfyUIWebSocketAPI(
            self.options.api_url.strip().replace('http://', '').strip('/'))

    def validate_parameters(self):
        """
        Validates that all required parameters are provided by the user.
        Raises:
            ValueError: If a required parameter is missing or no objects are selected.
        """
        required = {
            "positive_prompt": self.options.positive_prompt,
            "negative_prompt": self.options.negative_prompt,
            "workflow_json_path": self.get_workflow_path(),
            "api_url": self.options.api_url.strip(),
        }
        for key, value in required.items():
            if not value:
                inkex.errormsg(f"Please provide {key.replace('_', ' ')}.")
                raise ValueError(f"Missing parameter: {key}")

        if not self.svg.selected and not self.options.workflow_select == "basic":
            inkex.errormsg("Please select at least one object.")
            raise ValueError("No objects selected.")

    def export_objects(self, objects=None, prefix="input"):
        """
        Exports selected SVG objects to an image file for processing.

        Args:
            objects (list): List of objects to be exported
            prefix (str): Prefix of exported image.

        Returns:
            str: Path to the exported image file.
        Raises:
            ValueError: If no objects are selected.
            FileNotFoundError: If the export process fails.
        """
        temp_image_path = os.path.join(self.tempdir, f"{prefix}_image.png")

        if not objects:
            raise ValueError("No selected objects for export.")

        try:
            inkscape(
                self.options.input_file,
                "--export-type=png",
                f"--export-filename={temp_image_path}",
                "--export-id-only",
                f"--export-id={';'.join(objects)}",
                "--export-background-opacity=0.0"
            )
        except OSError as error:
            raise RuntimeError(f"Inkscape command failed: {error}")

        if not os.path.isfile(temp_image_path):
            raise FileNotFoundError(f"Export failed: {temp_image_path}")

        return temp_image_path

    def process_image(self, image_path, prefix="input", main_input_image=False):
        """
        Prepares the image by centering it on a square canvas.

        Args:
            image_path (str): Path to the exported image.

        Returns:
            str: Path to the processed square image.
        """
        image = Image.open(image_path)
        width, height = image.size
        longest_side = max(width, height)

        if main_input_image:
            self.longest_side = longest_side
            self.exported_width = width
            self.exported_height = height
        # else:
        #     width = width / (self.longest_side/longest_side)
        #     height = height / (self.longest_side/longest_side)
        #     image = image.resize((int(width), int(height)))

        image = image.convert("RGBA")

        square_image = Image.new("RGBA", (self.longest_side, self.longest_side), (0, 0, 0, 0))
        offset_x = (self.longest_side - width) / 2
        offset_y = (self.longest_side - height) / 2

        # Remove once we've got relative mask/pose positioning fixed.
        # inkex.utils.debug(f"{prefix}: {longest_side}")
        # inkex.utils.debug(f"{prefix}: {self.longest_side}")
        # inkex.utils.debug(f"{prefix}: {width}")
        # inkex.utils.debug(f"{prefix}: {height}")
        # inkex.utils.debug(f"{prefix}: {offset_x}")
        # inkex.utils.debug(f"{prefix}: {offset_y}")
        # inkex.utils.debug(f"{prefix}: {int(self.longest_side - offset_x)}")
        # inkex.utils.debug(f"{prefix}: {int(self.longest_side - offset_y)}")

        square_image.paste(
            image,
            (int(offset_x), int(offset_y)))
        # if main_input_image
        #     else (int(offset_x), int(offset_y), int(self.longest_side - offset_x), int(self.longest_side - offset_y)))


        square_image_path = os.path.join(self.tempdir, f"square_{prefix}_image.png")
        square_image.save(square_image_path)

        return square_image_path

    def process_mask(self, image_path, prefix="mask_input"):
        return self.process_image(image_path, prefix)

    def process_pose(self, image_path, prefix="pose_input"):
        return self.process_image(image_path, prefix)

    def load_workflow_json(self, workflow_json_path):
        """
        Loads a workflow JSON file.

        Args:
            workflow_json_path (str): Path to the workflow JSON file.

        Returns:
            dict: Parsed JSON data from the file.
        Raises:
            Exception: If the file cannot be read or parsed.
        """
        try:
            with open(workflow_json_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as error:
            inkex.errormsg(f"Workflow JSON file not found: {error}")
            raise
        except json.JSONDecodeError as error:
            inkex.errormsg(f"Invalid JSON format in workflow file: {error}")
            raise

    def populate_workflow(self, workflow_json):
        """
        Populates the workflow JSON with user inputs and processed image data.

        Args:
            workflow_json (dict): Workflow JSON data.

        Returns:
            dict: Updated workflow JSON data.
        """

        positive_id = str(self.get_workflow_option("positive_id"))
        negative_id = str(self.get_workflow_option("negative_id"))
        ksampler_id = str(self.get_workflow_option("ksampler_id"))

        workflow_json[positive_id]["inputs"]["text"] \
            = self.options.positive_prompt
        workflow_json[positive_id]['inputs']['text_l'] \
            = self.options.positive_prompt
        workflow_json[positive_id]['inputs']['text_g'] \
            = self.options.positive_prompt

        workflow_json[negative_id]["inputs"]["text"] \
            = self.options.negative_prompt
        workflow_json[negative_id]["inputs"]["text_l"] \
            = self.options.negative_prompt
        workflow_json[negative_id]["inputs"]["text_g"] \
            = self.options.negative_prompt

        workflow_json[ksampler_id]["inputs"].update({
            "cfg": self.options.cfg_scale,
            "denoise": self.options.denoise,
            "steps": self.options.steps,
            "seed": self.options.seed if self.options.seed > 0 else random.randint(0, 1000000000),
        })

        if self.options.workflow_select in ["img2img", "masked", "pose"]:
            image_input_id = str(self.get_workflow_option("image_input_id"))
            if int(image_input_id) > 0 and image_input_id in workflow_json:
                input_path = self.get_image_input_path(
                            self.get_image_objects(),
                            "image_input")
                # self.set_import_data(input_path)
                workflow_json[image_input_id]["inputs"]["image"] \
                    = self.comfy.load_image(input_path)

            if self.options.workflow_select == "masked":
                mask_input_id = str(self.get_workflow_option("mask_input_id"))
                if int(mask_input_id) > 0 and mask_input_id in workflow_json:
                    workflow_json[mask_input_id]["inputs"]["image"] \
                        = self.comfy.load_image(
                            self.get_mask_input_path(
                                self.get_mask_objects(),
                                "mask_input"))

            if self.options.workflow_select == "pose":
                pose_input_id = str(self.get_workflow_option("pose_input_id"))
                if int(pose_input_id) > 0 and pose_input_id in workflow_json:
                    workflow_json[pose_input_id]["inputs"]["image"] \
                        = self.comfy.load_image(
                            self.get_pose_input_path(
                                self.get_pose_objects(),
                                "pose_input"))

        return workflow_json

    def get_workflow_option(self, workflow_option):
        if workflow_option == "":
            return None

        workflow_option_key = f"{self.options.workflow_select}_{workflow_option}"
        return getattr(self.options, workflow_option_key, None)

    def get_image_objects(self):
        selected_ids = [node.get("id") for node in self.svg.selection]

        selected_ids = [id for id in selected_ids if not "__mask" in id and  not "__pose" in id]

        return selected_ids

    def get_mask_objects(self):
        if self.get_workflow_option("mask_input_id") == 0:
            return None

        selected_ids = [node.get("id") for node in self.svg.selection if "__mask" in node.get("id")]

        return selected_ids

    def get_pose_objects(self):
        if self.get_workflow_option("pose_input_id") == 0:
            return None

        selected_ids = [node.get("id") for node in self.svg.selection if "__mask" in node.get("id")]

        return selected_ids

    def get_image_input_path(self, objects, prefix):
        # Export selected SVG objects to an image
        exported_image_path = self.export_objects(objects, prefix)
        bboxes = [node.bounding_box() for node in self.svg.selection if node.get("id") in objects]

        # Process the exported image to fit requirements
        return self.process_image(exported_image_path, prefix, True)

    def get_mask_input_path(self, objects, prefix):
        # Export selected SVG objects to an image
        exported_image_path = self.export_objects(objects, prefix)
        bboxes = [node.bounding_box() for node in self.svg.selection if node.get("id") in objects]

        # Process the exported image to fit requirements
        return self.process_mask(exported_image_path, prefix)

    def get_pose_input_path(self, objects, prefix):
        # Export selected SVG objects to an image
        exported_image_path = self.export_objects(objects, prefix)
        bboxes = [node.bounding_box() for node in self.svg.selection if node.get("id") in objects]

        # Process the exported image to fit requirements
        return self.process_pose(exported_image_path, prefix)

    def get_workflow_path(self):
        if self.options.workflow_select == "basic" or self.options.workflow_select is None:
            return self.options.basic_workflow_json_path
        elif self.options.workflow_select == "img2img":
            return self.options.img2img_workflow_json_path
        elif self.options.workflow_select == "masked":
            return self.options.masked_workflow_json_path
        elif self.options.workflow_select == "pose":
            return self.options.pose_workflow_json_path

        return None

    def queue_prompt(self, prompt):
        """
        Queues a workflow prompt on the ComfyUI server.

        Args:
            prompt (dict): The workflow JSON data to be sent to the ComfyUI API.

        Returns:
            str: The ID of the queued prompt, used to retrieve results.

        Raises:
            urllib.error.URLError: If the request to the server fails.
            KeyError: If the response does not contain a 'prompt_id'.
        """
        # Send the modified workflow to the ComfyUI API
        prompt_endpoint = f"{self.options.api_url.strip()}prompt"

        # return comfy.queue_prompt(prompt)['prompt_id']
        prompt_json = {"prompt": prompt}
        data = json.dumps(prompt_json).encode('utf-8')
        # headers = {'Content-Type': 'application/json'}
        req = request.Request(prompt_endpoint, data=data)  # , headers=headers)
        try:
            with request.urlopen(req) as response:
                prompt_id = json.loads(response.read().decode('utf-8'))["prompt_id"]
                return prompt_id
        except urllib.error.URLError as error:
            inkex.errormsg(f"Network error while sending prompt: {error}")
            return None
        except json.JSONDecodeError as error:
            inkex.errormsg(f"Invalid JSON response from server: {error}")
            return None
        except KeyError as error:
            inkex.errormsg(f"Missing 'prompt_id' in response: {error}")
            return None

    def generate_result_image(self, workflow_json):
        """
        Generates an image using the ComfyUI API based on the provided workflow.

        Args:
            workflow_json (dict): Workflow JSON data.

        Returns:
            str: Path to the generated result image.
        """
        # Queue the prompt and get the job ID
        prompt_id = self.queue_prompt(workflow_json)
        if not prompt_id:
            return None

        # Poll the API for the result
        result_image_path = os.path.join(self.tempdir, 'result_image.png')

        history = self.comfy.get_history(prompt_id)

        while not prompt_id in history:
            history = self.comfy.get_history(prompt_id)
            time.sleep(1)

        history = history[prompt_id]

        output_images = []

        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output:
                for image in node_output['images']:
                    image_data = self.comfy.get_image(
                        image['filename'], image['subfolder'], image['type'])
                    output_images.append(image_data)

        image_data = output_images[0]
        with open(result_image_path, 'wb') as file:
            file.write(image_data)

        return result_image_path

    def insert_result_image(self, result_image_path, workflow_json):
        """
        Inserts the generated image into the SVG document, applying the necessary
        transformations and metadata.

        Args:
            result_image_path (str): Path to the generated image.
            workflow_json (dict): Workflow JSON data used to create the image.
        """
        # Open the result image
        result_image = Image.open(result_image_path)

        image_input_id = self.get_workflow_option("image_input_id")
        # Get the size of the exported image
        offset_x = 0
        offset_y = 0

        width, height = result_image.size

        if image_input_id and int(image_input_id) > 0:
            result_ratio = width / self.longest_side
            offset_x = (self.longest_side - self.exported_width) / 2
            offset_y = (self.longest_side - self.exported_height) / 2
        else:
            result_ratio = 1.0
            self.longest_side = max(width, height)
            self.exported_width = result_image.size[0]
            self.exported_height = result_image.size[1]

        # Crop the result image to the original bounding box dimensions
        cropped_result_image = result_image.crop(
            (
                int(offset_x * result_ratio),
                int(offset_y * result_ratio),
                int((self.longest_side - offset_x) * result_ratio),
                int((self.longest_side - offset_y) * result_ratio))
        )

        # Save the cropped image
        cropped_result_image_path = os.path.join(self.tempdir, 'cropped_result_image.png')
        cropped_result_image.save(cropped_result_image_path)

        # Insert the result image into the SVG
        # Calculate position and size based on the original selection
        if image_input_id and int(image_input_id) > 0:
            bbox = self.svg.selection.bounding_box()
            left = bbox.left
            top = bbox.top
            width = bbox.width
            height = bbox.height
        else:
            left = 0
            top = 0
            width = self.exported_width
            height = self.exported_height

        with open(cropped_result_image_path, 'rb') as image_file:
            # Encode the image in Base64
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

        # Create a new image element
        # Create a new image element with the Inkscape namespace
        image_elem = etree.Element(inkex.addNS('image', 'svg'), {
            'x': str(left),
            'y': str(top),
            'width': str(width),
            'height': str(height),
            '{http://www.w3.org/1999/xlink}href': f'data:image/png;base64,{encoded_image}'
        })

        # Add metadata to the SVG image element
        self.add_metadata(
            image_elem,
            workflow_json)

        # Add the image to the SVG
        self.svg.get_current_layer().append(image_elem)

    def add_metadata(self, image_elem, workflow_json):
        """
        Adds custom metadata to the generated SVG image element.

        Args:
            image_elem (etree.Element): The SVG image element to modify.
            workflow_json (dict): The workflow JSON data used to generate the image.
        """
        # Construct metadata dictionary
        metadata = {
            'positive_prompt': self.options.positive_prompt,
            'negative_prompt': self.options.negative_prompt,
            'cfg_scale': self.options.cfg_scale,
            'denoise': self.options.denoise,
            'seed': workflow_json[str(self.get_workflow_option("ksampler_id"))]["inputs"]['seed'],
            'steps': self.options.steps,
            'workflow_json_path': self.get_workflow_path(),
            'api_url': self.options.api_url.strip()
        }

        # Convert metadata to a JSON string
        metadata_json = json.dumps(metadata)

        # Set metadata attributes on the SVG element
        image_elem.set(
            f"{{{self.inkscape_ns}}}label",
            f"Generated Image: {self.options.positive_prompt}")

        image_elem.set(
            f"{{{self.inkscape_ns}}}custom_metadata",
            metadata_json)


if __name__ == '__main__':
    ComfyUIExtension().run()
