import os
import logging
import base64
from PIL import Image, ImageStat
from openai import OpenAI
from dotenv import load_dotenv
from typing import Dict, Any

load_dotenv()

logger = logging.getLogger(__name__)

class ImageAnalyzer:
    def __init__(self):
        self.openai_client = None
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.openai_client = OpenAI(api_key=api_key)
        else:
            logger.warning("OPENAI_API_KEY not found. Image analysis will be limited.")

    def get_image_metadata(self, image_path: str) -> Dict[str, Any]:
        """Extract basic technical specs using PIL."""
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                # Convert to grayscale to get brightness
                grayscale = img.convert('L')
                stat = ImageStat.Stat(grayscale)
                brightness = stat.mean[0]
                
                # Calculate sharpness (using variance of Laplacian style via standard deviation)
                sharpness = stat.stddev[0]
                # Normalize sharpness to a 0-100 score roughly
                sharpness_score = min(100, (sharpness / 64) * 100)

                aspect_ratio = width / height
                
                return {
                    "width": width,
                    "height": height,
                    "brightness": round(brightness, 2),
                    "aspect_ratio": round(aspect_ratio, 2),
                    "is_landscape": width > height,
                    "sharpness_score": round(sharpness_score, 2)
                }
        except Exception as e:
            logger.error(f"Error getting image metadata: {e}")
            return {}

    def analyze_with_gpt_vision(self, image_path: str, target_brand: str = None) -> Dict[str, Any]:
        """Use GPT-4o Vision for content analysis."""
        if not self.openai_client:
            return {"error": "OpenAI client not initialized"}

        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')

            prompt = (
                "You are an AI Image Analyzer. Analyze this image and respond ONLY in JSON format.\n\n"
                f"Target Brand to check: '{target_brand}'\n\n"
                "JSON Structure:\n"
                "{\n"
                "  \"type\": \"Type of image (e.g. promotional poster, infographic, meme, natural photo, screenshot)\",\n"
                "  \"description\": \"Brief visual description\",\n"
                "  \"extracted_text\": \"All visible text in the image\",\n"
                "  \"has_human_faces\": 0 or 1,\n"
                "  \"logo_visibility\": \"none\", \"low\", \"medium\", or \"high\",\n"
                "  \"brand_mention_found\": 0 or 1,\n"
                "  \"brand_compliance_summary\": \"How the brand is represented\",\n"
                "  \"image_vibrancy_score\": 0-100\n"
                "}"
            )

            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            import json
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"GPT Vision analysis failed: {e}")
            return {"error": str(e)}

    def analyze(self, image_path: str, target_brand: str = None) -> Dict[str, Any]:
        """Main entry point for image analysis."""
        metadata = self.get_image_metadata(image_path)
        vision_data = self.analyze_with_gpt_vision(image_path, target_brand)
        
        # Determine orientation label
        res_label = "Unknown"
        if metadata.get("width", 0) >= 1080 or metadata.get("height", 0) >= 1080:
            res_label = "1080p Full HD"
        elif metadata.get("width", 0) >= 720 or metadata.get("height", 0) >= 720:
            res_label = "720p HD"

        orientation = "square"
        if metadata.get("aspect_ratio", 1) > 1.1:
            orientation = "landscape"
        elif metadata.get("aspect_ratio", 1) < 0.9:
            orientation = "portrait"

        # Determine suitability
        is_suitable = True
        suitability_reasons = []
        
        if metadata.get("width", 0) < 1080 and metadata.get("height", 0) < 1080:
            is_suitable = False
            suitability_reasons.append("Low resolution (below 1080p)")
        
        if vision_data.get("brand_mention_found", 0) == 0 and target_brand:
            is_suitable = False
            suitability_reasons.append(f"Target brand '{target_brand}' not found in image")
            
        if metadata.get("brightness", 0) < 40:
            suitability_reasons.append("Image is quite dark")
        
        if metadata.get("sharpness_score", 0) < 40:
            is_suitable = False
            suitability_reasons.append("Image is blurry/low sharpness")

        suitability_message = "Suitable for posting." if is_suitable else "Potentially unsuitable for posting."
        if suitability_reasons:
            suitability_message += " Issues: " + ", ".join(suitability_reasons)

        # Format according to user's requested structure
        result = {
            "audio": {
                "has_audio": 0
            },
            "image": {
                "content": {
                    "type": vision_data.get("type", "unknown"),
                    "description": vision_data.get("description", ""),
                    "extracted_text": vision_data.get("extracted_text", ""),
                    "has_human_faces": vision_data.get("has_human_faces", 0),
                    "logo_visibility": vision_data.get("logo_visibility", "none"),
                    "image_vibrancy_score": vision_data.get("image_vibrancy_score", 0),
                    "suitability_score": 100 if is_suitable else 50,
                    "suitability_message": suitability_message
                },
                "is_image": 1,
                "brightness": metadata.get("brightness", 0),
                "resolution": {
                    "width": metadata.get("width", 0),
                    "height": metadata.get("height", 0)
                },
                "aspect_ratio": metadata.get("aspect_ratio", 1),
                "is_landscape": 1 if metadata.get("is_landscape") else 0,
                "sharpness_score": metadata.get("sharpness_score", 0)
            },
            "brand_compliance": {
                "summary": vision_data.get("brand_compliance_summary", ""),
                "transcript": vision_data.get("extracted_text", ""),
                "target_brand": target_brand,
                "mention_count": vision_data.get("brand_mention_found", 0),
                "logo_visibility": vision_data.get("logo_visibility", "none")
            },
            "technical_status": {
                "short_side": min(metadata.get("width", 0), metadata.get("height", 0)),
                "is_high_res": 1 if metadata.get("width", 0) >= 1080 or metadata.get("height", 0) >= 1080 else 0,
                "orientation": orientation,
                "aspect_ratio": metadata.get("aspect_ratio", 1),
                "resolution_label": res_label,
                "actual_resolution": f"{metadata.get('width', 0)}x{metadata.get('height', 0)}",
                "safe_area_warning": 0 if is_suitable else 1,
                "aspect_ratio_message": f"Suitable for Instagram {orientation.capitalize()}. {suitability_message}",
                "content_type_validated": "posts"
            }
        }
        
        return result
