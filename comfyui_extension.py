#!/usr/bin/env python3
import os
import json
import base64
import time
import inkex
import tempfile  # For temporary directory
import shutil    # For cleaning up
from inkex.command import inkscape  # Import inkscape command function
from urllib import request
from lxml import etree
import uuid
import urllib.request
import urllib.parse
from urllib.request import pathname2url
import random
import json
import requests
from PIL import Image
import io


class ComfyUIWebSocketAPI:
    def __init__(self, server_address="127.0.0.1:8188"):
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())

    def retry_request(self, url, data=None, headers={}, max_retries=5, backoff_factor=0.5):
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req) as response:
                    return response.read()
            except urllib.error.URLError as e:
                if attempt < max_retries - 1:
                    sleep_time = backoff_factor * (2 ** attempt)
                    time.sleep(sleep_time)
                else:
                    raise e

    def queue_prompt(self, prompt):
        p = {"prompt": prompt, "client_id": self.client_id}
        data = json.dumps(p).encode('utf-8')
        req = urllib.request.Request("http://{}/prompt".format(self.server_address), data=data)
        return json.loads(urllib.request.urlopen(req).read())

    def get_image(self, filename, subfolder, folder_type):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        with urllib.request.urlopen("http://{}/view?{}".format(self.server_address, url_values)) as response:
            return response.read()

    def get_history(self, prompt_id):
        url = "http://{}/history/{}".format(self.server_address, prompt_id)
        response = self.retry_request(url)
        # inkex.utils.debug(response)
        response_data = json.loads(response)

        return response_data

    def upload_file(self, file, subfolder="", overwrite=False):
        try:
            # Wrap file in formdata so it includes filename
            body = {"image": file}
            data = {}

            if overwrite:
                data["overwrite"] = "true"

            if subfolder:
                data["subfolder"] = subfolder

            resp = requests.post(f"http://{self.server_address}/upload/image", files=body, data=data)

            if resp.status_code == 200:
                data = resp.json()
                # Add the file to the dropdown list and update the widget value
                path = data["name"]
                if "subfolder" in data:
                    if data["subfolder"] != "":
                        path = data["subfolder"] + "/" + path


            else:
                inkex.utils.debug(f"{resp.status_code} - {resp.reason}")
        except Exception as error:
            inkex.utils.debug(error)
        return path

    def load_image(self, filepath):
        with open(filepath, "rb") as f:
            image = self.upload_file(f, "", True)
        return image

    def load_workflow(self, filepath):
        # load workflow from file
        with open(filepath, "r", encoding="utf-8") as f:
            workflow_data = f.read()

        return json.loads(workflow_data)


class ComfyUIExtension(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument(
            "--tab",
            default=self.tab_select,
            help="The selected UI-tab when OK was pressed",
        )

        pars.add_argument("--positive_prompt", type=str, help="Positive Prompt")
        pars.add_argument("--negative_prompt", type=str, help="Negative Prompt")
        pars.add_argument("--positive_id", type=int, default=6, help="Positive Prompt ID")
        pars.add_argument("--negative_id", type=int, default=7, help="Negative Prompt ID")
        pars.add_argument("--image_input_id", type=int, default=5, help="Image Input ID")
        pars.add_argument("--cfg_scale", type=float, default=7.0, help="CFG Scale")
        pars.add_argument("--denoise", type=float, default=0.75, help="Denoise")
        pars.add_argument("--seed", type=int, default=0, help="Seed")
        pars.add_argument("--steps", type=int, default=20, help="Steps")
        pars.add_argument("--ksampler_id", type=int, default=8, help="KSampler ID")
        pars.add_argument("--workflow_json_path", type=str, help="Workflow JSON Path")
        pars.add_argument("--api_url", type=str, default="127.0.0.1:8188", help="API URL")

    def tab_select(self, _):
        return "controls" if self.options.api_url and self.options.workflow_json_path else "comfy"

    def effect(self):
        # Define the Inkscape namespace
        inkscape_ns = "http://www.inkscape.org/namespaces/inkscape"

        # Register the namespace with a prefix
        etree.register_namespace('inkscape', inkscape_ns)

        # Access the first selected object
        first_selected = list(self.svg.selected.values())[0]

        # Retrieve custom metadata
        custom_metadata = None #first_selected.get(f'{{{inkscape_ns}}}custom_metadata')

        if custom_metadata:
            custom_metadata = json.loads(custom_metadata)

        # Get parameters

        tab = self.options.tab
        positive_prompt = self.options.positive_prompt if not custom_metadata else custom_metadata.positive_prompt
        negative_prompt = self.options.negative_prompt if not custom_metadata else custom_metadata.negative_prompt
        positive_id = str(self.options.positive_id)
        negative_id = str(self.options.negative_id)
        image_input_id = str(self.options.image_input_id)
        cfg_scale = float(self.options.cfg_scale) if not custom_metadata else custom_metadata.cfg_scale
        denoise = float(self.options.denoise) if not custom_metadata else custom_metadata.denoise
        seed = int(self.options.seed) if not custom_metadata else custom_metadata.seed
        steps = int(self.options.steps) if not custom_metadata else custom_metadata.steps
        ksampler_id = str(self.options.ksampler_id)
        workflow_json_path = self.options.workflow_json_path if not custom_metadata else custom_metadata.workflow_json_path
        api_url = self.options.api_url.strip() if not custom_metadata else custom_metadata.api_url.strip()

        # Validate parameters
        if not positive_prompt:
            inkex.errormsg("Please enter a positive prompt.")
            return

        if not negative_prompt:
            inkex.errormsg("Please enter a negative prompt.")
            return

        if not workflow_json_path:
            inkex.errormsg("Please provide a path to the workflow JSON file.")
            return

        if not api_url:
            inkex.errormsg("Please provide the API URL.")
            return

        # Check for selected objects
        if not self.svg.selected:
            inkex.errormsg("Please select at least one object.")
            return

        # Define the temporary directory
        self.tempdir = tempfile.mkdtemp()

        try:
            # Export selected objects as image
            temp_image_path = os.path.join(self.tempdir, 'exported_image.png')
            svg_file = self.options.input_file

            for node in self.svg.selection:
                if 'id' not in node.attrib:
                    # Assign a unique ID
                    node.attrib['id'] = f"object_{uuid.uuid4().hex}"

            selected_ids_list = [node.get('id') for node in self.svg.selection]
            # selected_ids_list = list(self.svg.selected.keys())

            inkex.utils.debug(temp_image_path)
            inkex.utils.debug(svg_file)
            inkex.utils.debug(selected_ids_list)
            # Get the bounding box of the selected objects
            bbox = self.svg.selection.bounding_box()

            # Use inkex.command.inkscape to run the export command
            try:
                ids = ';'.join(selected_ids_list)
                inkex.utils.debug(ids)
                inkscape(
                    svg_file,
                    '--export-type=png',
                    f'--export-filename={temp_image_path}',
                    '--export-id-only',
                    f'--export-id={ids}'
                )
            except Exception as e:
                inkex.errormsg(f"Error exporting image: {e}")
                return

            # Check if the exported image exists
            if not os.path.isfile(temp_image_path):
                inkex.errormsg(f"Exported image file not found at {temp_image_path}.")
                return

            # Open the exported image
            exported_image = Image.open(temp_image_path)

            # Get the size of the exported image
            exported_width, exported_height = exported_image.size

            # Determine the longest side to create a square canvas
            longest_side = max(exported_width, exported_height)

            # Create a new square image with transparent background
            square_image = Image.new("RGBA", (longest_side, longest_side), (0, 0, 0, 0))

            # Calculate the offset to center the exported image on the square canvas
            offset_x = (longest_side - exported_width) // 2
            offset_y = (longest_side - exported_height) // 2

            # Paste the exported image onto the square canvas
            square_image.paste(exported_image, (offset_x, offset_y))

            # Save the square image to a new path
            square_image_path = os.path.join(self.tempdir, 'square_image.png')
            square_image.save(square_image_path)

            # Load the workflow JSON
            try:
                with open(workflow_json_path, 'r') as f:
                    workflow_json = json.load(f)
            except Exception as e:
                inkex.errormsg(f"Error loading workflow JSON: {e}")
                return

            comfy = ComfyUIWebSocketAPI(api_url.replace('http://','').strip('/'))

            if positive_id in workflow_json and 'inputs' in workflow_json[positive_id]:
                workflow_json[positive_id]['inputs']['text_l'] = positive_prompt
                workflow_json[positive_id]['inputs']['text_g'] = positive_prompt
                workflow_json[positive_id]['inputs']['text'] = positive_prompt
            else:
                inkex.errormsg(f"Positive ID {positive_id} not found in workflow JSON.")
                inkex.utils.debug(workflow_json.get(positive_id))
                inkex.utils.debug(json.dumps(workflow_json))
                return

            # Set the negative prompt
            if negative_id in workflow_json and 'inputs' in workflow_json[negative_id]:
                workflow_json[negative_id]['inputs']['text_l'] = negative_prompt
                workflow_json[negative_id]['inputs']['text_g'] = negative_prompt
                workflow_json[negative_id]['inputs']['text'] = negative_prompt
            else:
                inkex.errormsg(f"Negative ID {negative_id} not found in workflow JSON.")
                inkex.utils.debug(json.dumps(workflow_json))
                return

            # Include the exported image
            if image_input_id in workflow_json and 'inputs' in workflow_json[image_input_id]:
                # with open(temp_image_path, 'rb') as image_file:
                #     encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                # # Assuming the node expects an image in base64 under the key 'image'
                workflow_json[image_input_id]['inputs']['image'] = comfy.load_image(square_image_path)
            else:
                inkex.errormsg(f"Image Input ID {image_input_id} not found in workflow JSON.")
                inkex.utils.debug(json.dumps(workflow_json))
                return

            if ksampler_id in workflow_json and 'inputs' in workflow_json[ksampler_id]:
                workflow_json[ksampler_id]['inputs']['cfg'] = cfg_scale
                workflow_json[ksampler_id]['inputs']['denoise'] = denoise
                workflow_json[ksampler_id]['inputs']['steps'] = steps
                workflow_json[ksampler_id]['inputs']['seed'] = seed
            else:
                inkex.errormsg(f"KSampler ID {ksampler_id} not found in workflow JSON.")
                return

            # Send the modified workflow to the ComfyUI API
            prompt_endpoint = f"{api_url}prompt"

            def queue_prompt(prompt):
                # return comfy.queue_prompt(prompt)['prompt_id']
                p = {"prompt": prompt}
                data = json.dumps(p).encode('utf-8')
                # headers = {'Content-Type': 'application/json'}
                req = request.Request(prompt_endpoint, data=data) #, headers=headers)
                try:
                    response = request.urlopen(req)
                    prompt_id = json.loads(response.read().decode('utf-8'))["prompt_id"]
                    return prompt_id
                except Exception as e:
                    inkex.errormsg(f"Error sending prompt to ComfyUI API: {e}")
                    inkex.utils.debug(json.dumps(workflow_json))
                    return None

            # Queue the prompt and get the job ID
            prompt_id = queue_prompt(workflow_json)
            if not prompt_id:
                return

            # Poll the API for the result
            result_image_path = os.path.join(self.tempdir, 'result_image.png')
            status_endpoint = f"{api_url}/status/{prompt_id}"

            history = comfy.get_history(prompt_id)

            while not prompt_id in history:
                history = comfy.get_history(prompt_id)
                time.sleep(1)

            history = history[prompt_id]

            # inkex.utils.debug(history)
            output_images = []

            for node_id in history['outputs']:
                node_output = history['outputs'][node_id]
                if 'images' in node_output:
                    for image in node_output['images']:
                        image_data = comfy.get_image(image['filename'], image['subfolder'], image['type'])
                        inkex.utils.debug(image)
                        # inkex.utils.debug(image_data)
                        output_images.append(image_data)

            image_data = output_images[0]
            with open(result_image_path, 'wb') as f:
                f.write(image_data)

            # Open the result image
            result_image = Image.open(result_image_path)

            # Get the size of the exported image
            result_width, result_height = result_image.size
            result_ratio = result_width / longest_side
            # Crop the result image to the original bounding box dimensions
            cropped_result_image = result_image.crop(
                (
                    int(offset_x * result_ratio),
                    int(offset_y * result_ratio),
                    int((offset_x + exported_width) * result_ratio),
                    int((offset_y + exported_height) * result_ratio))
                )

            # Save the cropped image
            cropped_result_image_path = os.path.join(self.tempdir, 'cropped_result_image.png')
            cropped_result_image.save(cropped_result_image_path)

            # Insert the result image into the SVG
            # Calculate position and size based on the original selection
            x = bbox.left
            y = bbox.top
            width = bbox.width
            height = bbox.height

            inkex.utils.debug(result_image_path)
            inkex.utils.debug(os.path.abspath(result_image_path))
            inkex.utils.debug(pathname2url(os.path.abspath(result_image_path)))
            inkex.utils.debug('file:' + pathname2url(os.path.abspath(result_image_path)))

            with open(cropped_result_image_path, 'rb') as image_file:
                image_data = image_file.read()

            # Encode the image in Base64
            encoded_image = base64.b64encode(image_data).decode('utf-8')

            # Create a new image element
            image_attribs = {
                'x': str(x),
                'y': str(y),
                'width': str(width),
                'height': str(height),
                '{http://www.w3.org/1999/xlink}href': f'data:image/png;base64,{encoded_image}'
            }
            # Create a new image element with the Inkscape namespace
            image_elem = etree.Element(inkex.addNS('image', 'svg'), image_attribs)

            # Create a dictionary of metadata
            metadata = {
                'positive_prompt': positive_prompt,
                'negative_prompt': negative_prompt,
                'cfg_scale': cfg_scale,
                'denoise': denoise,
                'seed': seed,
                'steps': steps,
                'workflow_json_path': workflow_json_path,
                'api_url': api_url
            }

            # Convert metadata to a JSON string
            metadata_json = json.dumps(metadata)

            # Attach metadata to the image element
            # Set the 'inkscape:label' attribute using the namespace
            image_elem.set(f'{{{inkscape_ns}}}label', f'Generated Image:{positive_prompt}')
            image_elem.set(f'{{{inkscape_ns}}}custom_metadata', metadata_json)

            # Add the image to the SVG
            self.svg.get_current_layer().append(image_elem)

            # Notify the user
            inkex.utils.debug("ComfyUI extension completed successfully. Result image inserted.")

        finally:
            # Clean up the temporary directory
            # shutil.rmtree(self.tempdir)
            pass


if __name__ == '__main__':
    ComfyUIExtension().run()