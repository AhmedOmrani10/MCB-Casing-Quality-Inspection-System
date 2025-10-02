
import time
import math
import threading
import numpy as np
import cv2
from picamera2 import Picamera2
from PIL import Image, ImageDraw, ImageFont
from luma.core.interface.serial import spi
from luma.lcd.device import st7789
import RPi.GPIO as GPIO

# -------------------------
# Pin configuration
# -------------------------
# Buttons
PIN_BTN_PREV = 27
PIN_BTN_NEXT = 17
PIN_BTN_OK   = 22

# Outputs / LEDs / control
PIN_CTRL   = 26  # original control pin (used earlier in your detection)
PIN_GREEN  = 5   # green LED
PIN_RED    = 6   # red LED

# TFT pins (for luma SPI)
TFT_DC  = 25
TFT_RST = 24
# Interrupt pin
PIN_INT    = 23  # external interrupt trigger (active high)
# -------------------------
# GPIO Setup
# -------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Buttons as inputs with pull-up
for p in (PIN_BTN_PREV, PIN_BTN_NEXT, PIN_BTN_OK):
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Outputs initialised to LOW
for p in (PIN_CTRL, PIN_GREEN, PIN_RED):
    GPIO.setup(p, GPIO.OUT)
    GPIO.output(p, GPIO.LOW)
# Interrupt pin (default 0V â†’ pulled down)
GPIO.setup(PIN_INT, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# Global interrupt flag
interrupt_triggered = threading.Event()

def handle_interrupt(channel):
    """Callback when interrupt pin goes HIGH"""
    interrupt_triggered.set()
# -------------------------
# Initialize TFT display
# -------------------------
serial = spi(port=0, device=0, gpio_DC=TFT_DC, gpio_RST=TFT_RST)
tft = st7789(serial, width=320, height=240, rotate=0)

# -------------------------
# Initialize Picamera2 (start in preview mode)
# -------------------------
picam2 = Picamera2()
try:
    preview_config = picam2.create_preview_configuration(main={"size": (320, 240)})
    picam2.configure(preview_config)
    picam2.start()
except Exception as e:
    print("Warning: camera preview configuration failed:", e)

# -------------------------
# Simple icon drawing helpers
# -------------------------
def create_icon(icon_type, size=24, color=(255,255,255)):
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    if icon_type == "detection":
        draw.ellipse([(4,4),(size-4,size-4)], outline=color, width=2)
        draw.ellipse([(8,8),(size-8,size-8)], fill=color)
    elif icon_type == "calibration":
        center = size//2
        r = size//3
        draw.ellipse([(center-r,center-r),(center+r,center+r)], outline=color, width=2)
        for i in range(8):
            a = i*(2*math.pi/8)
            x1 = center + int(r*math.cos(a))
            y1 = center + int(r*math.sin(a))
            x2 = center + int((r+5)*math.cos(a))
            y2 = center + int((r+5)*math.sin(a))
            draw.line([(x1,y1),(x2,y2)], fill=color, width=2)
    elif icon_type == "production":
        draw.rectangle([(4,4),(size-4,size-4)], outline=color, width=2)
        for i in range(1,3):
            y = 4 + i * ((size-8)//3)
            draw.line([(4,y),(size-4,y)], fill=color, width=1)
        for i in range(1,3):
            x = 4 + i * ((size-8)//3)
            draw.line([(x,4),(x,size-4)], fill=color, width=1)
    elif icon_type == "back":
        draw.polygon([(4,size//2),(size-4,4),(size-4,size-4)], fill=color)
    elif icon_type == "home":
        draw.polygon([(size//2,4),(4,size//2),(size-4,size//2)], fill=color)
        draw.rectangle([(size//4,size//2),(3*size//4,size-4)], fill=color)
    return img

ICONS = {
    "detection": create_icon("detection"),
    "calibration": create_icon("calibration"),
    "production": create_icon("production"),
    "back": create_icon("back"),
    "home": create_icon("home"),
}

# -------------------------
# ModernMenu class
# -------------------------
class ModernMenu:
    def __init__(self):
        self.options = [
            {"name":"Detection","icon":"detection"},
            {"name":"Calibration","icon":"calibration"},
            {"name":"Production","icon":"production"},
        ]
        self.selected_index = 0
        self.is_running = True
        self.current_screen = "menu"
        self.animation_offset = 0.0

        # Button event driven variable (set by GPIO callbacks)
        self.lock = threading.Lock()
        self.button_event = None     # 'prev', 'next', 'ok' or None

        # Debounce protection for poll-based fallback
        self.last_button_check = time.time()
        self.button_debounce_time = 0.2

        # Fonts
        try:
            self.title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
            self.option_font = ImageFont.truetype("DejaVuSans.ttf", 16)
            self.small_font = ImageFont.truetype("DejaVuSans.ttf", 12)
        except Exception:
            self.title_font = ImageFont.load_default()
            self.option_font = ImageFont.load_default()
            self.small_font = ImageFont.load_default()

    # callback entrance for GPIO events
    def handle_button_press(self, btn_name):
        with self.lock:
            # store the last event; main loop will process it
            self.button_event = btn_name

    def _pop_button_event(self):
        with self.lock:
            ev = self.button_event
            self.button_event = None
            return ev

    def draw_background(self, draw, width, height):
        # simple vertical gradient
        for y in range(height):
            r = int(20 + (y / height) * 10)
            g = int(25 + (y / height) * 15)
            b = int(40 + (y / height) * 30)
            draw.line([(0,y),(width,y)], fill=(r,g,b))

    def draw_menu(self):
        image = Image.new("RGB", (tft.width, tft.height), "black")
        draw = ImageDraw.Draw(image)
        self.draw_background(draw, tft.width, tft.height)

        header_h = 40
        draw.rectangle((0,0,tft.width,header_h), fill=(30,35,45))
        title = "VISION SYSTEM"
        try:
            tw = draw.textlength(title, font=self.title_font)
            draw.text(((tft.width-tw)//2,10), title, font=self.title_font, fill=(220,220,220))
        except:
            draw.text(((tft.width-100)//2,10), title, fill=(220,220,220))

        option_h = 45
        spacing = 10
        total_h = len(self.options)*option_h + (len(self.options)-1)*spacing
        start_y = (tft.height - header_h - 30 - total_h)//2 + header_h

        for i,opt in enumerate(self.options):
            y = start_y + i*(option_h + spacing)
            icon = ICONS[opt["icon"]]
            if i == self.selected_index:
                draw.rounded_rectangle((20,y,tft.width-20,y+option_h), radius=12, fill=(65,105,225),
                                       outline=(100,150,255), width=2)
                image.paste(icon, (40, y+10), icon)
                try:
                    draw.text((80,y+15), opt["name"], font=self.option_font, fill=(255,255,255))
                except:
                    draw.text((80,y+15), opt["name"], fill=(255,255,255))
                draw.polygon([(25,y+20),(35,y+10),(35,y+30)], fill=(255,255,255))
            else:
                draw.rounded_rectangle((20,y,tft.width-20,y+option_h), radius=12, fill=(50,55,65),
                                       outline=(80,85,95), width=1)
                image.paste(icon, (40, y+10), icon)
                try:
                    draw.text((80,y+15), opt["name"], font=self.option_font, fill=(200,200,200))
                except:
                    draw.text((80,y+15), opt["name"], fill=(200,200,200))

        footer_h = 30
        draw.rectangle((0,tft.height-footer_h,tft.width,tft.height), fill=(30,35,45))
        instr = "UP/DOWN: Navigate    CENTER: Select"
        try:
            iw = draw.textlength(instr, font=self.small_font)
            draw.text(((tft.width-iw)//2, tft.height-20), instr, font=self.small_font, fill=(180,180,180))
        except:
            draw.text((20, tft.height-20), instr, fill=(180,180,180))

        tft.display(image)
        self.animation_offset += 0.1

    def show_loading_screen(self, title):
        image = Image.new("RGB", (tft.width, tft.height), "black")
        draw = ImageDraw.Draw(image)
        self.draw_background(draw, tft.width, tft.height)
        cx, cy = tft.width//2, tft.height//2
        r = 30
        for i in range(8):
            a = self.animation_offset + (i*(2*math.pi/8))
            x = cx + int(r*math.cos(a))
            y = cy + int(r*math.sin(a))
            draw.ellipse((x-5,y-5,x+5,y+5), fill=(65,105,225))
        try:
            tw = draw.textlength(title, font=self.title_font)
            draw.text(((tft.width-tw)//2, cy+50), title, font=self.title_font, fill=(220,220,220))
        except:
            draw.text(((tft.width-100)//2, cy+50), title, fill=(220,220,220))
        tft.display(image)
        self.animation_offset += 0.2

    def show_header(self, draw, title, show_back=True):
        header_h = 40
        draw.rectangle((0,0,tft.width,header_h), fill=(30,35,45))
        if show_back:
            back_icon = ICONS["back"]
            # draw.bitmap not always available; paste with alpha
            image = draw.im  # internal PIL ImageDraw accesses .im
            try:
                # small hack: paste icon on underlying image object
                draw._image.paste(back_icon, (10,10), back_icon)
            except Exception:
                # fallback to draw a simple triangle for back
                draw.polygon([(10, header_h//2),(20,10),(20,header_h-10)], fill=(200,200,200))
        try:
            tw = draw.textlength(title, font=self.title_font)
            draw.text(((tft.width-tw)//2,10), title, font=self.title_font, fill=(220,220,220))
        except:
            draw.text(((tft.width-100)//2,10), title, fill=(220,220,220))
        return header_h

    # Navigation helpers
    def navigate_up(self):
        self.selected_index = (self.selected_index - 1) % len(self.options)
        self.draw_menu()

    def navigate_down(self):
        self.selected_index = (self.selected_index + 1) % len(self.options)
        self.draw_menu()

    def select_option(self):
        sel = self.options[self.selected_index]["name"]
        print("Selected:", sel)
        #self.show_loading_screen(f"Starting {sel}")
        time.sleep(0.7)
        if sel == "Detection":
            self.run_detection()
        elif sel == "Calibration":
            self.run_calibration()
        elif sel == "Production":
            self.run_production()
        # after action, return to menu
        self.current_screen = "menu"
        self.draw_menu()

    def run_calibration(self):
        self.current_screen="calibration"
        try:
           picam2.stop()
        except:
              pass
        try:
            calib_cfg = picam2.create_video_configuration(main={"size":(320,240)})
            picam2.configure(calib_cfg)
            picam2.start()
        except Exception as e :
            print("faild to configure camera for calibration")
        try:
            while self.current_screen =="calibration":
                frame =picam2.capture_array()
                if frame.ndim == 3 and frame.shape[2] == 3:
                    frame = frame[:, :, ::-1]  # BGR -> RGB

					
                frame_resized =cv2.resize(frame,(320,240))
                tft_image =Image.fromarray(frame_resized)
                image = Image.eval(tft_image, lambda x: 255 - x)

                tft.display(image)
                ev =self._pop_button_event()
                if ev=='prev':
                    self.current_screen ="menu"
                    break
                elif ev=='ok':
                     pass
        except Exception as e:
             print(e)
        finally:
            try:
                picam2.stop()
            except:
                pass
            try:
                preview_cfg = picam2.create_video_configuration(main={"size":(320,240)})
                picam2.configuure(preview_cfg)
                picam2.start()
            except Exception as e:
                print("Faild to return to preview after calibration",e)
            print("Exiting calibration,returning to menu")
				
				
			
        

    def run_production(self):
        self.current_screen = "production"
        image = Image.new("RGB",(tft.width,tft.height),"black")
        draw = ImageDraw.Draw(image)
        self.draw_background(draw, tft.width, tft.height)
        header_h = self.show_header(draw, "PRODUCTION")
        metrics_y = header_h + 20
        for count in range(1,11):
            if self.current_screen != "production":
                break
            # redraw background and header
            draw.rectangle([0, header_h+1, tft.width, tft.height], fill="black")
            self.draw_background(draw, tft.width, tft.height)
            self.show_header(draw, "PRODUCTION")
            draw.text((30, metrics_y), f"Units Produced: {count}", fill=(220,220,220))
            draw.text((30, metrics_y+30), f"Quality: {95 - (count % 5)}%", fill=(220,220,220))
            draw.text((30, metrics_y+60), "Status: Running", fill="green")
            for i in range(3):
                y_pos = metrics_y + 100 + i*20
                width = 80 + int(40 * math.sin(time.time() * 2 + i))
                draw.rectangle([40, y_pos, 40+width, y_pos+12], fill=(65,105,225))
            tft.display(image)
            time.sleep(0.5)
            # check button events
            ev = self._pop_button_event()
            if ev == 'prev':
                self.current_screen = "menu"
                break
        if self.current_screen == "production":
            draw.rectangle([0, header_h+1, tft.width, tft.height], fill="black")
            self.draw_background(draw, tft.width, tft.height)
            self.show_header(draw, "PRODUCTION")
            draw.text((40,120), "Production Cycle Complete!", fill="green")
            draw.text((60,150), "10 units produced", fill="white")
            tft.display(image)
            time.sleep(2)

    # central button check (polling fallback + processes events set by interrupts)
    def check_buttons(self):
        # Prioritize event-driven button
        ev = self._pop_button_event()
        if ev:
            # handle event
            if ev == 'prev':
                if self.current_screen == "menu":
                    self.navigate_up()
                else:
                    # in submenu back to menu
                    self.current_screen = "menu"
                    self.draw_menu()
                return True
            elif ev == 'next':
                if self.current_screen == "menu":
                    self.navigate_down()
                return True
            elif ev == 'ok':
                if self.current_screen == "menu":
                    self.select_option()
                return True

        # Polling fallback (in case event detect missed)
        now = time.time()
        if now - self.last_button_check < self.button_debounce_time:
            return False
        self.last_button_check = now

        # check physical pins (active low)
        if GPIO.input(PIN_BTN_PREV) == 0:
            if self.current_screen == "menu":
                self.navigate_up()
            else:
                self.current_screen = "menu"
                self.draw_menu()
            return True
        if GPIO.input(PIN_BTN_NEXT) == 0:
            if self.current_screen == "menu":
                self.navigate_down()
            return True
        if GPIO.input(PIN_BTN_OK) == 0:
            if self.current_screen == "menu":
                self.select_option()
            return True
        return False

    # -------------------------
    # Detection routine (fully integrated)
    # -------------------------
    def run_detection(self):
        print("Entering detection")
        self.current_screen = "detection"

        # Reconfigure camera to video size (stop/start required)
        try:
            picam2.stop()
        except Exception:
            pass
        try:
            video_cfg = picam2.create_video_configuration(main={"size": (640,480)})
            picam2.configure(video_cfg)
            picam2.start()
        except Exception as e:
            print("Failed to configure camera for video:", e)

        # Detection parameters
        yellow_lower = np.array([20, 100, 100], np.uint8)
        yellow_upper = np.array([30, 255, 255], np.uint8)
        kernel = np.ones((5,5), np.uint8)

        try:
            while self.current_screen == "detection":
                # capture frame (Picamera2 returns RGB)
                frame = picam2.capture_array()

                # Convert RGB -> BGR for OpenCV operations
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                # Convert to HSV and create mask
                hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
                mask = cv2.inRange(hsv, yellow_lower, yellow_upper)
                mask = cv2.dilate(mask, kernel, iterations=1)
                mask = cv2.erode(mask, kernel, iterations=1)

                # find contours
                contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                valid_contours = 0
                for cnt in contours:
                    area = cv2.contourArea(cnt)
                    if area > 50:
                        valid_contours += 1
                        x,y,w,h = cv2.boundingRect(cnt)
                        cv2.rectangle(frame_bgr, (x,y), (x+w, y+h), (0,255,255), 2)
                        cv2.putText(frame_bgr, f"Yellow ({int(area)})", (x, y-10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)
                        cx = x + w//2
                        cy = y + h//2
                        cv2.circle(frame_bgr, (cx,cy), 5, (0,0,255), -1)
                        cv2.putText(frame_bgr, f"({cx},{cy})", (cx+8, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

                # --- Control GPIOs only if interrupt triggered ---
                if interrupt_triggered.is_set():
                    if valid_contours == 2:
                        # ok
                        GPIO.output(PIN_CTRL, GPIO.LOW)
                        GPIO.output(PIN_GREEN, GPIO.HIGH)
                        GPIO.output(PIN_RED, GPIO.LOW)
                    else:
                        # not ok
                        GPIO.output(PIN_CTRL, GPIO.HIGH)
                        GPIO.output(PIN_GREEN, GPIO.LOW)
                        GPIO.output(PIN_RED, GPIO.HIGH)

                    # reset flag so outputs only update once per interrupt
                    interrupt_triggered.clear()

                # Put some status text on frame
                cv2.putText(frame_bgr, f"Contours: {valid_contours}", (10,30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
                cv2.putText(frame_bgr, "Press Prev to return", (10,60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)

                # Convert BGR -> RGB for display
                display_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                tft_frame = cv2.resize(display_frame, (320,240))
                tft_image = Image.fromarray(tft_frame)
                # invert colors if your display gave negative images
                tft_image = Image.eval(tft_image, lambda x: 255 - x)

                tft.display(tft_image)

                # process any button event (interrupt-driven)
                ev = self._pop_button_event()
                if ev == 'prev':
                    # user asked to return to menu
                    self.current_screen = "menu"
                    break
                elif ev == 'next':
                    # optionally use next for other function
                    pass
                elif ev == 'ok':
                    # optionally use ok inside detection
                    pass

                # fallback poll check to be extra robust
                self.check_buttons()

                # slight delay
                time.sleep(0.03)

        except Exception as e:
            print("Detection loop error:", e)
        finally:
            # ensure LEDs off and camera reconfigured back to preview
            GPIO.output(PIN_CTRL, GPIO.LOW)
            GPIO.output(PIN_GREEN, GPIO.LOW)
            GPIO.output(PIN_RED, GPIO.LOW)

            try:
                picam2.stop()
            except Exception:
                pass

            # go back to preview config for menu
            try:
                preview_cfg = picam2.create_preview_configuration(main={"size": (320,240)})
                picam2.configure(preview_cfg)
                picam2.start()
            except Exception as e:
                print("Failed to return camera to preview:", e)

            print("Exiting detection, returning to menu.")

# -------------------------
# Main program
# -------------------------
def main():
    menu = ModernMenu()
    # register event-detect callbacks (use lambda to pass menu handle)
    GPIO.add_event_detect(PIN_BTN_PREV, GPIO.FALLING, callback=lambda ch: menu.handle_button_press('prev'), bouncetime=100)
    GPIO.add_event_detect(PIN_BTN_NEXT, GPIO.FALLING, callback=lambda ch: menu.handle_button_press('next'), bouncetime=300)
    GPIO.add_event_detect(PIN_BTN_OK,   GPIO.FALLING, callback=lambda ch: menu.handle_button_press('ok'),   bouncetime=300)
    # attach interrupt on pin 23
    GPIO.add_event_detect(PIN_INT, GPIO.RISING, callback=handle_interrupt, bouncetime=200)

    # show initial menu
    menu.draw_menu()

    try:
        while menu.is_running:
            # process any button events / polling fallback
            menu.check_buttons()
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("Interrupted by user")

    finally:
        # cleanup
        try:
            GPIO.remove_event_detect(PIN_BTN_PREV)
            GPIO.remove_event_detect(PIN_BTN_NEXT)
            GPIO.remove_event_detect(PIN_BTN_OK)
        except Exception:
            pass

        try:
            picam2.stop()
        except Exception:
            pass

        try:
            # clear display
            tft.display(Image.new("RGB", (tft.width, tft.height), (0,0,0)))
        except Exception:
            pass

        GPIO.output(PIN_CTRL, GPIO.LOW)
        GPIO.output(PIN_GREEN, GPIO.LOW)
        GPIO.output(PIN_RED, GPIO.LOW)
        GPIO.cleanup()
        print("Goodbye!")

if __name__ == "__main__":
    main()
