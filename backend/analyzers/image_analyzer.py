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

            brand_context = f"Target Brand: '{target_brand}'" if target_brand else "No specific brand target."
            prompt = (
                "You are an expert AI Image Quality Auditor. Analyze this image for social media suitability.\n\n"
                f"{brand_context}\n\n"
                "TASKS:\n"
                "1. Identify the type of content (e.g., product photo, lifestyle, graphic design).\n"
                "2. Extract all visible text (OCR).\n"
                "3. Analyze LOGOS: Detect any brand logos. If the target brand is provided, check if it's present.\n"
                "4. LOGO DETAILS: Note the placement (e.g., top-left, center), size (relative to image), and prominence.\n"
                "5. QUALITY: Judge vibrancy, composition, and professional feel.\n\n"
                "Respond ONLY in JSON format:\n"
                "{\n"
                "  \"type\": \"string\",\n"
                "  \"description\": \"string\",\n"
                "  \"extracted_text\": \"string\",\n"
                "  \"has_human_faces\": 0 or 1,\n"
                "  \"brand_found\": boolean,\n"
                "  \"logo_details\": {\n"
                "     \"visibility\": \"none|low|medium|high\",\n"
                "     \"placement\": \"string\",\n"
                "     \"is_obstructed\": boolean,\n"
                "     \"is_prominent\": boolean\n"
                "  },\n"
                "  \"vibrancy_score\": 0-100,\n"
                "  \"composition_score\": 0-100,\n"
                "  \"professional_feel_score\": 0-100,\n"
                "  \"brand_compliance_summary\": \"string\"\n"
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
                max_tokens=600,
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
        
        # Determine resolution label
        width, height = metadata.get("width", 0), metadata.get("height", 0)
        res_label = "SD"
        if width >= 1080 or height >= 1080:
            res_label = "1080p Full HD"
        elif width >= 720 or height >= 720:
            res_label = "720p HD"

        orientation = "square"
        aspect_ratio = metadata.get("aspect_ratio", 1)
        if aspect_ratio > 1.1: orientation = "landscape"
        elif aspect_ratio < 0.9: orientation = "portrait"

        # --- SCORING SYSTEM ---
        # 1. Technical (40%): Sharpness + Resolution
        res_score = min(100, (max(width, height) / 1080) * 100)
        sharp_score = metadata.get("sharpness_score", 0)
        tech_score = (res_score * 0.4) + (sharp_score * 0.6)
        
        # 2. Aesthetic (30%): GPT Vibrancy + Composition
        aes_score = (vision_data.get("vibrancy_score", 50) * 0.5) + (vision_data.get("composition_score", 50) * 0.5)
        
        # 3. Brand (30%): Logo visibility + Prominence
        # IMPORTANT: Force logo_visibility to none if brand_found is false
        brand_found = vision_data.get("brand_found", False)
        logo_details = vision_data.get("logo_details", {})
        if not brand_found:
            logo_details["visibility"] = "none"
            logo_details["is_prominent"] = False
            logo_details["placement"] = "N/A"

        logo_map = {"none": 0, "low": 30, "medium": 70, "high": 100}
        logo_base = logo_map.get(logo_details.get("visibility", "none"), 0)
        if logo_details.get("is_prominent", False):
            logo_base = min(100, logo_base + 20)
        
        # If target brand is expected but not found, brand score is 0
        if target_brand and not brand_found:
            brand_score = 0
        else:
            brand_score = logo_base if target_brand else 100 # If no target, we assume generic quality
            
        overall_score = (tech_score * 0.4) + (aes_score * 0.3) + (brand_score * 0.3)

        # Issues collection
        issues = []
        if sharp_score < 40: issues.append({"type": "image", "severity": "high", "message": "Image is blurry/low sharpness"})
        if max(width, height) < 1080: issues.append({"type": "image", "severity": "medium", "message": "Resolution is below 1080p"})
        if metadata.get("brightness", 0) < 40: issues.append({"type": "image", "severity": "low", "message": "Image is quite dark"})
        if target_brand and not brand_found:
            issues.append({"type": "image", "severity": "high", "message": f"Target brand '{target_brand}' not visible in image"})

        # Format according to user's requested structure
        result = {
            "overall_score": round(overall_score, 2),
            "audio": {"has_audio": 0},
            "image": {
                "content": {
                    "type": vision_data.get("type", "unknown"),
                    "description": vision_data.get("description", ""),
                    "extracted_text": vision_data.get("extracted_text", ""),
                    "has_human_faces": vision_data.get("has_human_faces", 0),
                    "logo_details": logo_details,
                    "image_vibrancy_score": vision_data.get("vibrancy_score", 0),
                    "composition_score": vision_data.get("composition_score", 0),
                    "overall_quality_score": round(overall_score, 2)
                },
                "is_image": 1,
                "brightness": metadata.get("brightness", 0),
                "resolution": {"width": width, "height": height},
                "aspect_ratio": aspect_ratio,
                "is_landscape": 1 if metadata.get("is_landscape") else 0,
                "sharpness_score": round(sharp_score, 2),
                "issues": issues
            },
            "brand_compliance": {
                "summary": vision_data.get("brand_compliance_summary", ""),
                "transcript": vision_data.get("extracted_text", ""),
                "target_brand": target_brand,
                "mention_count": 1 if brand_found else 0,
                "logo_visibility": logo_details.get("visibility", "none")
            },
            "technical_status": {
                "short_side": min(width, height),
                "is_high_res": 1 if max(width, height) >= 1080 else 0,
                "orientation": orientation,
                "aspect_ratio": aspect_ratio,
                "resolution_label": res_label,
                "actual_resolution": f"{width}x{height}",
                "safe_area_warning": 1 if issues else 0,
                "aspect_ratio_message": f"Format: {orientation.capitalize()}. " + (issues[0]["message"] if issues else "Perfect for social posting."),
                "content_type_validated": "posts"
            }
        }
        
        return result
