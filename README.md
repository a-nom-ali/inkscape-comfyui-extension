# inkscape-comfui-extension
An Inkscape extension that integrates ComfyUI - turning Inkscape into Recraft, but with all Inkscape's features!

The **Inkscape ComfyUI Extension** integrates Inkscape with the ComfyUI API, enabling users to generate images based on selected SVG objects and specified prompts. This extension facilitates the creation of AI-generated images directly within Inkscape, streamlining the design workflow.

## Key Features:
 * AI Image Generation: Transform selected SVG elements into AI-generated images using custom positive and negative prompts.
 * Seamless Integration: Directly interact with the ComfyUI API from within Inkscape.
 * Customizable Parameters: Adjust settings such as CFG Scale, Denoise, Seed, and Steps to fine-tune image generation.
 * Workflow Management: Load and utilize predefined workflows in JSON format.

## Dependencies:
 * Inkscape: Version 1.3.2 or higher.
 * ComfyUI API: Accessible at the specified API URL (default: 127.0.0.1:8188).

## Compatibility:
 * Operating Systems: Compatible with Windows, macOS, and Linux.
 * Inkscape Versions: Designed for Inkscape 1.0 and above.

## Installation:
1. Set Up ComfyUI API: Ensure the ComfyUI API is running and accessible at the specified API URL.
2. Install Inkscape
3. Install Extension: Place the extension files in Inkscape’s user extensions directory. You can find this folder in:

      - Edit>Preferences or Inkscape>Settings on Mac
      - Select System
      - Press the **"Open"** button next to "User extensions"
4. Restart Inkscape: Restart Inkscape to load the new extension.
5. Use the Extension: Select SVG objects, navigate to the extension, input prompts and parameters, and generate images.

## Setup:
1. An api version workflow is included - check to make sure you have all the right models by opening it in ComfyUI.
   * Or use your own after saving it to API format.
2. The features are currently limited to:
     * A positive prompt
     * A negative prompt
     * An image input
     * A KSampler's:
       * CFG Scale
       * Denoise
       * Seed
       * Steps
3. You need to find the correct IDs in the JSON file and set those in the IDs tab.
   * These IDs will differ from what you see in your normal (non-api) workflow in ComfyUI, so remember to check.
4. If your ComfyUI IP or port differs, update to match.
   * If ComfyUI is on a different PC on your network, remember to start it with the argument: 
   > "--listen 0.0.0.0"
5. Remember to follow the above process when you change the workflow. Would be nice to improve this to a history - help welcome!

## Usage:
1. Draw something or select an existing object.
2. Extensions>Render>ComfyUI
3. If you haven't done the setup, do so now
3. Enter your prompt and select your values
4. Press Apply
5. Wait for ComfyUI to finish producing your results
6. Rave in awe!

### Additionally
* Once you have the image, it is a simple matter of tracing the bitmap. You can find this feature at **Path>Trace Bitmap**. Play around with the settings.
* It often helps to take the results and use that with the same prompt to refine the outcome - play around!


## Security Considerations:
 * API Interactions: The extension communicates with the ComfyUI API via HTTP requests. Ensure the API URL is correctly configured and secure.
 * File Handling: Temporary files are created during image processing. The extension manages these files securely, but users should be aware of their system’s temporary directory policies.

## Tags:
 * AI
 * Image Generation
 * ComfyUI
 * Inkscape Extension
 * Design Tool


By integrating AI-driven image generation into Inkscape, this extension enhances creative workflows, offering designers a powerful tool to expand their design capabilities.