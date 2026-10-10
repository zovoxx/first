
import json, os
import comfy_pipe as cp

ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Contoo", "Assets")


def cutout(image_rel, prefix):
    wf = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_rel}},
        "2": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": "birefnet.safetensors"}},
        "3": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "InvertMask", "inputs": {"mask": ["3", 0]}},
        "5": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["1", 0], "alpha": ["4", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["5", 0]}},
    }
    return cp.submit(wf)


def triposplat(image_rel, prefix, seed=46, n_pc=262144, n_mobile=65536, preview_frames=4):
    wf = {
        "99": {"class_type": "LoadImage", "inputs": {"image": image_rel}},
        "82": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": "birefnet.safetensors"}},
        "81": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["82", 0], "image": ["99", 0]}},
        "2": {"class_type": "TripoSplatPreprocessImage", "inputs": {"erode_radius": 1, "size": 1024, "image": ["99", 0], "mask": ["81", 0]}},
        "7": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "dino_v3_vit_h.safetensors"}},
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "triposplat_vae_decoder_fp16.safetensors"}},
        "16": {"class_type": "UNETLoader", "inputs": {"unet_name": "triposplat_fp16.safetensors", "weight_dtype": "default"}},
        "24": {"class_type": "TripoSplatConditioning", "inputs": {"clip_vision": ["7", 0], "vae": ["8", 0], "image": ["2", 0]}},
        "6": {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": 20, "cfg": 3, "sampler_name": "dpmpp_2m", "scheduler": "simple", "denoise": 1,
                                                   "model": ["16", 0], "positive": ["24", 0], "negative": ["24", 1], "latent_image": ["24", 2]}},
        "55": {"class_type": "VAEDecodeTripoSplat", "inputs": {"num_gaussians": int(n_pc), "seed": 790219963981395, "samples": ["6", 0], "vae": ["11", 0]}},
        "56": {"class_type": "VAEDecodeTripoSplat", "inputs": {"num_gaussians": int(n_mobile), "seed": 790219963981395, "samples": ["6", 0], "vae": ["11", 0]}},
        "92": {"class_type": "SplatToFile3D", "inputs": {"format": "spz", "splat": ["55", 0]}},
        "93": {"class_type": "SplatToFile3D", "inputs": {"format": "spz", "splat": ["56", 0]}},
        "94": {"class_type": "SplatToFile3D", "inputs": {"format": "ply", "splat": ["56", 0]}},
        "51": {"class_type": "SaveGLB", "inputs": {"filename_prefix": prefix + "_PC", "image": "", "mesh": ["92", 0]}},
        "52": {"class_type": "SaveGLB", "inputs": {"filename_prefix": prefix + "_mobile", "image": "", "mesh": ["93", 0]}},
        "53": {"class_type": "SaveGLB", "inputs": {"filename_prefix": prefix + "_ply", "image": "", "mesh": ["94", 0]}},
        "79": {"class_type": "CreateCameraInfo", "inputs": {"mode": "orbit", "mode.yaw": 35, "mode.pitch": 30, "mode.distance": 2.5,
                                                            "target_x": 0, "target_y": 0, "target_z": 0, "roll": 0, "fov": 35, "zoom": 1,
                                                            "camera_type": "perspective"}},
        "75": {"class_type": "RenderSplat", "inputs": {"width": 768, "height": 768, "frames": int(preview_frames), "splat_scale": 1, "sharpen": 2,
                                                       "headlight_shading": 0, "opacity_threshold": 0, "render_style": "color",
                                                       "background": "#848484", "splat": ["55", 0], "camera_info": ["79", 0]}},
        "76": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix + "_preview", "images": ["75", 0]}},
    }
    return cp.submit(wf)


def acestep(tags, bpm, keyscale, seconds, prefix, seed=0, lyrics="[Instrumental]", timesig="4"):
    wf = {
        "104": {"class_type": "UNETLoader", "inputs": {"unet_name": "acestep_v1.5_xl_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "105": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "qwen_0.6b_ace15.safetensors", "clip_name2": "qwen_4b_ace15.safetensors",
                                                           "type": "ace", "device": "default"}},
        "106": {"class_type": "VAELoader", "inputs": {"vae_name": "ace_1.5_vae.safetensors"}},
        "78": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3, "sampling": "flow", "model": ["104", 0]}},
        "94": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {"tags": tags, "lyrics": lyrics, "seed": int(seed), "bpm": int(bpm),
                                                                      "duration": int(seconds), "timesignature": timesig, "language": "en",
                                                                      "keyscale": keyscale, "generate_audio_codes": True, "cfg_scale": 2,
                                                                      "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0, "clip": ["105", 0]}},
        "47": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["94", 0]}},
        "98": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": int(seconds), "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": 8, "cfg": 1, "sampler_name": "euler", "scheduler": "simple",
                                                   "denoise": 1, "model": ["78", 0], "positive": ["94", 0], "negative": ["47", 0],
                                                   "latent_image": ["98", 0]}},
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["106", 0]}},
        "111": {"class_type": "SaveAudioAdvanced", "inputs": {"filename_prefix": prefix, "format": "mp3", "format.quality": "V0", "audio": ["18", 0]}},
    }
    return cp.submit(wf)
