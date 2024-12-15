from math import floor
from PIL import Image
import requests
from io import BytesIO
import cv2
import json
import os
import hashlib
from pathlib import Path
import uuid
import time
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()

frame_width = 1080
frame_height = 1920

frame_center = [frame_width/2, frame_height/2]
full_frame_container_dimensions = [frame_width, frame_height]

upper_container_dimensions = [frame_width, frame_height/2]
lower_container_dimensions = [frame_width, frame_height/2]

upper_container_center = [frame_width/2, frame_height/4]
lower_container_center = [frame_width/2, frame_height/4*3]

# Create cache directory if it doesn't exist
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

def get_cached_file_path(url):
    # Create a unique filename using URL hash
    url_hash = hashlib.md5(url.encode()).hexdigest()
    file_ext = url.split('.')[-1].lower()
    return CACHE_DIR / f"{url_hash}.{file_ext}"

def download_and_cache(url):
    cache_path = get_cached_file_path(url)
    
    # If file exists in cache, return the cached path
    if cache_path.exists():
        return str(cache_path)
    
    # Download and save to cache
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(cache_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        return str(cache_path)
    except Exception as e:
        print(f"Error downloading {url}: {str(e)}")
        return None
    
def get_video_duration(actor_video_url):
    """Get the duration of a video file in milliseconds"""
    try:
        video_path = download_and_cache(actor_video_url)
        video = cv2.VideoCapture(video_path)
        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = (frame_count / fps) * 1000  # Convert to milliseconds
        video.release()
        return int(duration)
    except Exception as e:
        print(f"Error getting video duration: {str(e)}")
        return 30000  # Default duration if unable to get actual duration

def get_position_and_scale(container_center, asset_url, z_index, fit_dimension='auto', rotation=0, is_full_frame=False):
    try:
        # Get cached file path or download
        local_path = download_and_cache(asset_url)
        if not local_path:
            raise Exception("Failed to download or retrieve from cache")
        
        file_ext = asset_url.split('.')[-1].lower()
        
        if file_ext in ['jpg', 'jpeg', 'png', 'gif']:
            media = Image.open(local_path)
            width, height = media.size
            
        elif file_ext in ['mp4', 'mov', 'avi', 'webm']:
            video = cv2.VideoCapture(local_path)
            width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
            video.release()
            
            # If video dimensions couldn't be read, use default dimensions
            if width == 0 or height == 0:
                width, height = frame_width, frame_height
                
        elif file_ext in ['mp3', 'wav', 'aac']:
            width, height = 100, 100
            
        else:
            width, height = frame_width, frame_height

        # Use full frame dimensions if is_full_frame is True
        container_dims = full_frame_container_dimensions if is_full_frame else upper_container_dimensions

        # Calculate scale based on fit_dimension
        if fit_dimension == 'width':
            scale = container_dims[0] / width
        elif fit_dimension == 'height':
            scale = container_dims[1] / height
        else:
            # If no fit_dimension specified, fit based on larger dimension
            width_scale = container_dims[0] / width
            height_scale = container_dims[1] / height
            scale = width_scale if width >= height else height_scale
        
        return {
            "position": {
                "x": container_center[0],
                "y": container_center[1],
                "z": z_index
            },
            "transform": {
                "scale": {
                    "x": scale,
                    "y": scale
                },
                "rotation": rotation
            },
            "size": {
                "width": width,
                "height": height
            }
        }
    except Exception as e:
        print(f"Error processing {asset_url}: {str(e)}")
        return {
            "position": {
                "x": container_center[0],
                "y": container_center[1],
                "z": z_index
            },
            "transform": {
                "scale": {
                    "x": 1,
                    "y": 1
                },
                "rotation": rotation
            },
            "size": {
                "width": frame_width,
                "height": frame_height
            }
        }

# Video structure:
# First 5s: Actor video
# Middle: Alternating between AA (two assets) and AD (asset + actor) patterns
# Last 5s: Actor video

only_actor_time = 5000

def create_video_json(actor_video_url, total_duration, assets, background_color_hex="#000000"):
    # Download files first...
    print("Caching actor video...")
    download_and_cache(actor_video_url)
    
    print("Caching assets...")
    for asset_url in assets:
        download_and_cache(asset_url)
    
    n = len(assets)
    P = floor(n/3)
    AD = n - 2*P
    AA = P
    no_of_screens = (AA+AD)
    duration_of_asset_screens = (total_duration - 2*only_actor_time) / no_of_screens
    
    clips = []
    
    # First 5 seconds - Actor video (full screen)
    actor_start = get_position_and_scale(frame_center, actor_video_url, 0, 'height', 0, True)
    clips.append({
        "id": str(uuid.uuid4()),
        "type": "video",
        "name": actor_video_url.split('/')[-1],
        "source": actor_video_url,
        "timeFrame": {
            "start": 0,
            "end": only_actor_time,
            "offset": 0
        },
        "position": actor_start["position"],
        "volume": 1,
        "transform": actor_start["transform"],
        "size": actor_start["size"]
    })
    
    current_time = only_actor_time
    asset_index = 0
    
    # Alternate between AA and AD patterns
    remaining_aa = AA
    remaining_ad = AD
    
    while remaining_aa > 0 or remaining_ad > 0:
        # Handle AA pattern
        if remaining_aa > 0:
            # Add solid background color clip for AA pattern
            clips.append({
                "id": str(uuid.uuid4()),
                "type": "image",
                "name": "background",
                "source": "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/05b4fbc3f169175e6deb97b3977175b6.jpg",
                "timeFrame": {
                    "start": current_time,
                    "end": current_time + duration_of_asset_screens
                },
                "position": {
                    "x": frame_width/2,
                    "y": frame_height/2,
                    "z": 1
                },
                "transform": {
                    "scale": {
                        "x": 1,
                        "y": 1
                    },
                    "rotation": 0
                },
                "size": {
                    "width": frame_width,
                    "height": frame_height
                }
            })
            
            # First asset in upper container
            upper_asset = get_position_and_scale(upper_container_center, assets[asset_index], 2)
            clips.append({
                "id": str(uuid.uuid4()),
                "type": "video" if assets[asset_index].lower().endswith(('mp4', 'mov', 'avi', 'webm')) else "image",
                "name": assets[asset_index].split('/')[-1],
                "source": assets[asset_index],
                "timeFrame": {
                    "start": current_time,
                    "end": current_time + duration_of_asset_screens
                },
                "position": upper_asset["position"],
                "volume": 1,
                "transform": upper_asset["transform"],
                "size": upper_asset["size"]
            })
            
            # Second asset in lower container
            asset_index += 1
            lower_asset = get_position_and_scale(lower_container_center, assets[asset_index], 2)
            clips.append({
                "id": str(uuid.uuid4()),
                "type": "video" if assets[asset_index].lower().endswith(('mp4', 'mov', 'avi', 'webm')) else "image",
                "name": assets[asset_index].split('/')[-1],
                "source": assets[asset_index],
                "timeFrame": {
                    "start": current_time,
                    "end": current_time + duration_of_asset_screens
                },
                "position": lower_asset["position"],
                "volume": 1,
                "transform": lower_asset["transform"],
                "size": lower_asset["size"]
            })
            asset_index += 1
            current_time += duration_of_asset_screens
            remaining_aa -= 1
        
        # Handle AD pattern
        if remaining_ad > 0:
            # Asset in upper container
            upper_asset = get_position_and_scale(upper_container_center, assets[asset_index], 2)
            clips.append({
                "id": str(uuid.uuid4()),
                "type": "video" if assets[asset_index].lower().endswith(('mp4', 'mov', 'avi', 'webm')) else "image",
                "name": assets[asset_index].split('/')[-1],
                "source": assets[asset_index],
                "timeFrame": {
                    "start": current_time,
                    "end": current_time + duration_of_asset_screens
                },
                "position": upper_asset["position"],
                "volume": 1,
                "transform": upper_asset["transform"],
                "size": upper_asset["size"]
            })
            
            # If this is the first AD pattern, add the continuous actor video
            if remaining_ad == AD:
                actor_clip = get_position_and_scale(lower_container_center, actor_video_url, 0)
                clips.append({
                    "id": str(uuid.uuid4()),
                    "type": "video",
                    "name": actor_video_url.split('/')[-1],
                    "source": actor_video_url,
                    "timeFrame": {
                        "start": only_actor_time,
                        "end": total_duration - only_actor_time,
                        "offset": max(0, only_actor_time - 0.1)
                    },
                    "position": actor_clip["position"],
                    "volume": 1,
                    "transform": actor_clip["transform"],
                    "size": actor_clip["size"]
                })
            
            asset_index += 1
            current_time += duration_of_asset_screens
            remaining_ad -= 1
    
    # Last 5 seconds - Actor video (full screen)
    actor_end = get_position_and_scale(frame_center, actor_video_url, 0, 'height', 0, True)
    clips.append({
        "id": str(uuid.uuid4()),
        "type": "video",
        "name": actor_video_url.split('/')[-1],
        "source": actor_video_url,
        "timeFrame": {
            "start": total_duration - only_actor_time,
            "end": total_duration,
            "offset": total_duration - only_actor_time
        },
        "position": actor_end["position"],
        "volume": 1,
        "transform": actor_end["transform"],
        "size": actor_end["size"]
    })
    
    result = {
        "metadata": {
            "backgroundColor": background_color_hex,  # Updated to use passed background color
            "duration": total_duration,
            "fps": 25,
            "canvas": {
                "width": frame_width,
                "height": frame_height
            },
            "name": "Reels AI Template"
        },
        "clips": clips
    }
    
    # Save to JSON file
    with open('video_template.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    return result

def render_video(video_json: Dict) -> Optional[str]:
    """
    Send a POST request to initiate video rendering
    
    Args:
        video_json (Dict): The video template JSON
    
    Returns:
        Optional[str]: The render ID if successful, None otherwise
    """
    API_KEY = os.environ.get('VIDEOAIDITOR_API_KEY')
    if not API_KEY:
        print("Error: VIDEOAIDITOR_API_KEY environment variable not set")
        return None
    
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': API_KEY
    }
    
    # Prepare the request payload
    payload = {
        # "renderOptionsInUI": [],
        "metadata": video_json["metadata"],
        "clips": video_json["clips"],
        # "additional": {},
        # "autoGenerateCaptionWords": False,
        # "captionLanguageCode": "en-US"
    }
    
    try:
        response = requests.post(
            'https://api.videoaiditor.com/v1/renders',
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        
        render_id = response.json()['data']['_id']
        print(f"Render initiated with ID: {render_id}")
        return render_id
        
    except requests.exceptions.RequestException as e:
        print(f"Error initiating render: {str(e)}")
        return None

def monitor_render_progress(render_id: str, max_attempts: int = 60) -> Optional[str]:
    """
    Monitor the rendering progress and return the output URL when complete
    
    Args:
        render_id (str): The render ID to monitor
        max_attempts (int): Maximum number of attempts to check status (default: 60)
    
    Returns:
        Optional[str]: The output URL if successful, None otherwise
    """
    API_KEY = os.environ.get('VIDEOAIDITOR_API_KEY')
    if not API_KEY:
        print("Error: VIDEOAIDITOR_API_KEY environment variable not set")
        return None
    
    headers = {
        'x-api-key': API_KEY
    }
    
    attempt = 0
    while attempt < max_attempts:
        try:
            response = requests.get(
                f'https://api.videoaiditor.com/v1/renders/{render_id}',
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()['data']
            status = data.get('status')
            
            if status == 'completed':
                output_url = data.get('outputUrl')
                print(f"\nRendering completed!")
                print(f"Output URL: {output_url}")
                return output_url
            
            elif status == 'failed':
                error = data.get('error', 'Unknown error')
                print(f"\nRendering failed: {error}")
                return None
            
            else:
                print(f"Rendering in progress... Status: {status}")
                time.sleep(60)  # Wait 60 seconds before next check
                attempt += 1
                
        except requests.exceptions.RequestException as e:
            print(f"Error checking render status: {str(e)}")
            return None
    
    print("Timeout: Maximum attempts reached")
    return None


def create_and_render_video(actor_url: str, total_duration: int, assets: list) -> Optional[str]:
    """
    Create video JSON and initiate rendering
    
    Returns:
        Optional[str]: The output URL if successful, None otherwise
    """
    # Create video JSON template
    video_json = create_video_json(actor_url, total_duration, assets)
    
    # Initiate rendering
    render_id = render_video(video_json)
    if not render_id:
        return None
    
    # Monitor progress and get output URL
    return monitor_render_progress(render_id)

if __name__ == "__main__":
    actor_url = "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/4cd491c7-f68c-46e1-9cda-089a883076d0.mp4"
    total_duration = get_video_duration(actor_video_url=actor_url) 
    assets = [
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/72ac7657-7164-4442-bb4e-15851e9fc4e8.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/573135ba-9dcb-4690-993b-5bc943c36582.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/667545c5-1ae7-4c15-b2fc-dad6920a8adb.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/a0352f12-ff7c-4e0f-88ea-4437ccb8f4a4.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/4e667862-ba03-4184-bd92-94a913a6605a.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/0f1dd400-5d9d-451e-93f5-ec49e3be8b96.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/86ac3bfe-b121-4865-a6a8-4c7b85735743.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/57bfc58c-4662-4066-85ed-61a5c5b19a96.jpg",
        "https://aiditor-uploads.s3.ap-south-1.amazonaws.com/uploads/3f7bbb22-7b7a-4023-9f42-058b66605b73.jpg"
    ]

    output_url = create_and_render_video(actor_url, total_duration, assets)
    if output_url:
        print(f"\nFinal video URL: {output_url}")
