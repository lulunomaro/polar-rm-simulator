"""Spectator-only current red camera viewpoint with measured projectile trails.

The main panel is an ideal unwarped observer view, not the detector input.
Inset is the actual last delivered/captured native RGB, downsampled for display.
"""
import mujoco,numpy as np
from PIL import Image,ImageDraw

class CameraObserver:
    def __init__(self,sim):self.renderer=mujoco.Renderer(sim.model,720,960)
    def frame(self,sim,source):
        self.renderer.update_scene(sim.data,camera='red_sentry__aim');sim.draw_projectiles(self.renderer.scene)
        if sim.spectator_effects:sim.spectator_effects.draw(self.renderer.scene)
        canvas=Image.new('RGB',(960,800),(12,17,25));canvas.paste(Image.fromarray(self.renderer.render()),(0,80))
        d=ImageDraw.Draw(canvas)
        d.text((14,10),f'RED SENTRY OPTICAL VIEW | SIM {sim.time:.3f}s | '+(source.status if source else 'baseline'),fill='white')
        d.text((14,30),'OBSERVER ONLY: unwarped ideal view; trails connect actual projectile samples; impact markers enlarged.',fill=(255,210,120))
        d.text((14,50),'No trajectories/markers enter detector input. Raw native input appears as inset while stationary.',fill='white')
        if source and source.client and source.latest_rgb is not None:
            canvas.paste(Image.fromarray(source.latest_rgb).resize((288,216)),(660,580))
            d.text((667,583),'RAW NATIVE RGB (scaled)',fill=(80,255,100))
        return np.asarray(canvas)
    def close(self):self.renderer.close()
