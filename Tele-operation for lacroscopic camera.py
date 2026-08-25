import os
import time
import sys
import ctypes
import math
import keyboard 
from dobot_sdk import DobotRobot, CoordinateType

# ==========================================
# 🛑 1. HAPTIC DLL INJECTION (MUST BE HERE)
# ==========================================
os.add_dll_directory(r"C:\Program Files\3D Systems\Touch Device Drivers\OpenHaptics_Demos\HapticDemo\HapticDemo_Data\Plugins\x86_64")

# ==========================================
# ⚙️ CONFIGURATION & SPEED SETTINGS
# ==========================================
ROBOT_IP = "192.168.0.4"
WAIT_TIME = 2.0          # Pause between waypoint steps (seconds)

# 🚀 Waypoint Motion Speed (start, home, pos4)
WAYPOINT_SPEED_FACTOR = 15 # 🎚️ Point-to-point movement speed (1% to 100%)

# 🕹️ Teleoperation Speed & Motion Rates
TELE_SPEED_FACTOR = 3     # 🎚️ Speed percentage during teleoperation
TELE_SCALE = 0.5           # Stylus movement scaling factor
ROTATION_SCALE = 1.0       # Stylus orientation scaling factor
KEYBOARD_STEP = 4.0        # Step size (mm) for keyboard triggers (W/S, R/F, Y/H)

MAX_STEP_MM = 5.0          # Max positional movement per tick (mm) - Increased for faster movement
MAX_STEP_DEG = 4.0         # Max rotational movement per tick (deg)
JOG_REFRESH = 0.03         # Stream refresh rate (seconds)

# 💧 Medium Viscosity Tuning
VISCOSITY_COEFFICIENT = 0.035 

# 📍 Predefined Waypoints
POSITIONS = [
    [-231.14, 229.8, 235.10, 93.0, -49.2, 178.0],  # Position 1 (Home)
    [-419.56,  418.94,  806.72, -94.78, -69.0, 2.52],     # Position 2 
    [-445.37,  219.16,  811.60, -96.63, -65, 10],     # Position 3 
    [-493.0,  116.51,  754.40, -165.81, 0.4, 93.0]      # Position 4 
]

# ==========================================
# 🛠️ PURE CTYPES HAPTIC ENGINE SETUP (6-DOF)
# ==========================================
dll_path = r"C:\Program Files\3D Systems\Touch Device Drivers\OpenHaptics_Demos\HapticDemo\HapticDemo_Data\Plugins\x86_64\hd.dll"
hd_lib = ctypes.CDLL(dll_path)

HD_CURRENT_POSITION = 0x2050
HD_CURRENT_GIMBAL_ANGLES = 0x2150  # Rx, Ry, Rz orientation
HD_CURRENT_BUTTONS = 0x2000        # Stylus button bitmask constant
HD_CURRENT_FORCE = 0x2700          # Force feedback output register
HD_CALLBACK_CONTINUE = 1

class HDErrorInfo(ctypes.Structure):
    _fields_ = [
        ("errorCode", ctypes.c_int),
        ("internalCode", ctypes.c_int),
        ("hHD", ctypes.c_int)
    ]

hd_lib.hdInitDevice.restype = ctypes.c_int
hd_lib.hdInitDevice.argtypes = [ctypes.c_void_p]
hd_lib.hdStartScheduler.restype = None
hd_lib.hdStopScheduler.restype = None

CALLBACK_FUNC_TYPE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
hd_lib.hdScheduleAsynchronous.restype = ctypes.c_uint
hd_lib.hdScheduleAsynchronous.argtypes = [CALLBACK_FUNC_TYPE, ctypes.c_void_p, ctypes.c_int]
hd_lib.hdUnschedule.argtypes = [ctypes.c_uint]
hd_lib.hdBeginFrame.argtypes = [ctypes.c_int]
hd_lib.hdEndFrame.argtypes = [ctypes.c_int]
hd_lib.hdGetDoublev.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
hd_lib.hdGetIntegerv.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
hd_lib.hdSetDoublev.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
hd_lib.hdDisableDevice.argtypes = [ctypes.c_int]
hd_lib.hdGetError.restype = HDErrorInfo

class StylusState:
    x = 0.0
    y = 0.0
    z = 0.0
    rx = 0.0
    ry = 0.0
    rz = 0.0
    buttons = 0
    prev_x = 0.0
    prev_y = 0.0
    prev_z = 0.0

stylus_state = StylusState()
hHD_global = 0
callback_handle = 0

@CALLBACK_FUNC_TYPE
def position_callback(user_data):
    global stylus_state, hHD_global
    try:
        hd_lib.hdBeginFrame(hHD_global)
        
        # 1. Read XYZ Position
        pos = (ctypes.c_double * 3)()
        hd_lib.hdGetDoublev(HD_CURRENT_POSITION, pos)
        
        vx = pos[0] - stylus_state.prev_x
        vy = pos[1] - stylus_state.prev_y
        vz = pos[2] - stylus_state.prev_z
        
        stylus_state.prev_x = pos[0]
        stylus_state.prev_y = pos[1]
        stylus_state.prev_z = pos[2]
        
        stylus_state.x = pos[0]
        stylus_state.y = pos[1]
        stylus_state.z = pos[2]
        
        # 2. Read Rx, Ry, Rz Gimbal Angles
        gimbal = (ctypes.c_double * 3)()
        hd_lib.hdGetDoublev(HD_CURRENT_GIMBAL_ANGLES, gimbal)
        stylus_state.rx = gimbal[0]
        stylus_state.ry = gimbal[1]
        stylus_state.rz = gimbal[2]
        
        # 3. Read Buttons
        btn = ctypes.c_int()
        hd_lib.hdGetIntegerv(HD_CURRENT_BUTTONS, ctypes.byref(btn))
        stylus_state.buttons = btn.value
        
        # 4. Apply Viscosity
        force = (ctypes.c_double * 3)(
            -VISCOSITY_COEFFICIENT * vx,
            -VISCOSITY_COEFFICIENT * vy,
            -VISCOSITY_COEFFICIENT * vz
        )
        hd_lib.hdSetDoublev(HD_CURRENT_FORCE, force)
        
        hd_lib.hdEndFrame(hHD_global)
    except:
        pass
    return HD_CALLBACK_CONTINUE

def setup_haptic():
    global hHD_global, callback_handle
    print("Connecting to 3D Systems Touch via pure ctypes...")
    try:
        hHD = hd_lib.hdInitDevice(None)
        hHD_global = hHD
        
        err = hd_lib.hdGetError()
        if err.errorCode != 0 or hHD == -1:
            print(f"⚠️ Haptic Connection Failed. Error Code: {err.errorCode}")
            return False
            
        hd_lib.hdStartScheduler()
        callback_handle = hd_lib.hdScheduleAsynchronous(position_callback, None, 0)
        
        print("✅ Haptic Device Connected with Full 6-DOF Active!")
        return True
    except Exception as e:
        print(f"⚠️ Haptic Connection Failed: {e}")
        return False

def close_haptic():
    global hHD_global, callback_handle
    try:
        if callback_handle:
            hd_lib.hdUnschedule(callback_handle)
        hd_lib.hdStopScheduler()
        if hHD_global:
            hd_lib.hdDisableDevice(hHD_global)
        print("✅ Haptic device closed cleanly.")
    except:
        pass

# ==========================================
# 🛡️ ROBUST ROBOT SYSTEM FUNCTIONS
# ==========================================
def reset_motion_state(robot):
    """Flushes active servo streaming buffers and restores speed factor for standard moves."""
    try:
        robot.motion.Stop()
        time.sleep(0.3)
        robot.robot_control.RequestControl()
        time.sleep(0.3)
        robot.robot_control.ClearError()
        time.sleep(0.3)
        robot.robot_control.EnableRobot()
        time.sleep(0.5)
        robot.robot_control.SpeedFactor(WAYPOINT_SPEED_FACTOR)
        time.sleep(0.3)
    except Exception as e:
        print(f"⚠️ Motion state reset warning: {e}")

def force_move_to_pos4(robot):
    """Parks at Position 4 with automatic 2-stage recovery if singularity occurs."""
    print("🛡️ Resetting controller state and returning to Position 4...")
    reset_motion_state(robot)
    
    try:
        robot.motion.MovJ(pose=POSITIONS[3], coord_type=CoordinateType.CARTESIAN)
        time.sleep(3.0)
        print("✅ Robot successfully parked at Position 4.")
        return True
    except Exception as e:
        print(f"⚠️ Direct move to Position 4 failed ({e}). Executing two-stage safety recovery...")
        
        reset_motion_state(robot)
        
        try:
            print("Stage 1: Moving to Position 3 first for Z-height clearance...")
            robot.motion.MovJ(pose=POSITIONS[2], coord_type=CoordinateType.CARTESIAN)
            time.sleep(2.5)
            
            print("Stage 2: Moving to Position 4...")
            robot.motion.MovJ(pose=POSITIONS[3], coord_type=CoordinateType.CARTESIAN)
            time.sleep(2.5)
            print("✅ Robot successfully parked at Position 4.")
            return True
        except Exception as stage2_err:
            print(f"❌ Safety recovery failed: {stage2_err}")
            reset_motion_state(robot)
            return False

def safe_move(robot, target_pose):
    try:
        robot.robot_control.SpeedFactor(WAYPOINT_SPEED_FACTOR)
        robot.motion.MovJ(pose=target_pose, coord_type=CoordinateType.CARTESIAN)
        return True
    except Exception as e:
        print(f"\n⚠️ [MOVE ERROR]: {e}")
        print("Retrying movement after control state reset...")
        try:
            reset_motion_state(robot)
            robot.motion.MovJ(pose=target_pose, coord_type=CoordinateType.CARTESIAN)
            return True
        except Exception as retry_err:
            print(f"❌ Retry failed: {retry_err}")
            return force_move_to_pos4(robot)

def unwind_to_home(robot):
    print("\nUnwinding arm back to Home (Position 1) safely...")
    
    if not safe_move(robot, POSITIONS[3]):
        if not force_move_to_pos4(robot):
            return False
    time.sleep(WAIT_TIME)
    
    # Iterate through waypoints in reverse (Position 4 -> 3 -> 2 -> 1)
    for idx, pose in enumerate(reversed(POSITIONS)):
        print(f"Unwinding step {idx + 1}/{len(POSITIONS)}...")
        if not safe_move(robot, pose):
            print("❌ Homing failed. Parked at Position 4.")
            return False
        time.sleep(WAIT_TIME)

    print("✅ Arrived safely at Home (Position 1)!")
    return True

# ==========================================
# 🎮 REAL-TIME CARTESIAN TELEOPERATION (SERVOP)
# ==========================================
def run_teleoperation(robot, start_pose):
    print(f"\n--- 🕹️ TELEOPERATION MODE ACTIVE (Speed: {TELE_SPEED_FACTOR}%) ---")
    print("  ⌨️ KEYBOARD CONTROLS:")
    print("     • X-Axis : 'W' (+X) / 'S' (-X)")
    print("     • Y-Axis : 'R' (+Y) / 'F' (-Y)")
    print("     • Z-Axis : 'Y' (+Z) / 'H' (-Z)")
    print("  🖋️ STYLUS CONTROLS:")
    print("     • Hold Stylus Button (or Spacebar) to drive X, Y, Rx, Ry, Rz")
    print("  🛑 PRESS AND HOLD 'Q' TO EXIT TELEOPERATION.")
    print("-----------------------------------------------------------------")
    
    try:
        robot.robot_control.SpeedFactor(TELE_SPEED_FACTOR)
    except:
        pass

    current_pose = start_pose.copy()
    
    prev_x = stylus_state.x
    prev_y = stylus_state.y
    prev_rx = stylus_state.rx
    prev_ry = stylus_state.ry
    prev_rz = stylus_state.rz

    while True:
        if keyboard.is_pressed('q'):
            print("\nExiting Haptic Tele Mode...")
            reset_motion_state(robot)
            return current_pose

        curr_x = stylus_state.x
        curr_y = stylus_state.y
        curr_rx = stylus_state.rx
        curr_ry = stylus_state.ry
        curr_rz = stylus_state.rz

        is_button_held = (stylus_state.buttons & 1) != 0 or keyboard.is_pressed('space')

        dx, dy, dz = 0.0, 0.0, 0.0
        drx, dry, drz = 0.0, 0.0, 0.0

        # 1. Stylus Motion Input (when button is held)
        if is_button_held:
            dx_raw = (curr_x - prev_x) * TELE_SCALE
            dy_raw = (curr_y - prev_y) * TELE_SCALE

            dx += max(min(dx_raw, MAX_STEP_MM), -MAX_STEP_MM)
            dy += max(min(dy_raw, MAX_STEP_MM), -MAX_STEP_MM)

            drx_raw = math.degrees(curr_rx - prev_rx) * ROTATION_SCALE
            dry_raw = math.degrees(curr_ry - prev_ry) * ROTATION_SCALE
            drz_raw = math.degrees(curr_rz - prev_rz) * ROTATION_SCALE

            drx = max(min(drx_raw, MAX_STEP_DEG), -MAX_STEP_DEG)
            dry = max(min(dry_raw, MAX_STEP_DEG), -MAX_STEP_DEG)
            drz = max(min(drz_raw, MAX_STEP_DEG), -MAX_STEP_DEG)

        # 2. Direct Keyboard Controls Override/Combine
        if keyboard.is_pressed('w'):   dx += KEYBOARD_STEP
        elif keyboard.is_pressed('s'): dx -= KEYBOARD_STEP

        if keyboard.is_pressed('r'):   dy += KEYBOARD_STEP
        elif keyboard.is_pressed('f'): dy -= KEYBOARD_STEP

        if keyboard.is_pressed('y'):   dz += KEYBOARD_STEP
        elif keyboard.is_pressed('h'): dz -= KEYBOARD_STEP

        has_movement = (dx != 0.0 or dy != 0.0 or dz != 0.0 or drx != 0.0 or dry != 0.0 or drz != 0.0)

        print(f"Teleop -> dX:{dx:4.1f} dY:{dy:4.1f} dZ:{dz:4.1f} | dRx:{drx:4.1f} dRy:{dry:4.1f} dRz:{drz:4.1f}", end='\r')

        if has_movement:
            target_pose = current_pose.copy()
            
            target_pose[0] += dx
            target_pose[1] += dy
            target_pose[2] += dz
            target_pose[3] += drx
            target_pose[4] += dry
            target_pose[5] += drz
            
            try:
                robot.motion.ServoP(pose=target_pose)
                current_pose = target_pose
                prev_x = curr_x
                prev_y = curr_y
                prev_rx = curr_rx
                prev_ry = curr_ry
                prev_rz = curr_rz
            except Exception as e:
                print(f"\n⚠️ ServoP streaming error: {e}")
                
            time.sleep(JOG_REFRESH)
        else:
            prev_x = curr_x
            prev_y = curr_y
            prev_rx = curr_rx
            prev_ry = curr_ry
            prev_rz = curr_rz
            time.sleep(0.02)

# ==========================================
# 🚀 MAIN APPLICATION LOOP
# ==========================================
def main():
    haptic_success = setup_haptic()
    
    print(f"Connecting to Dobot CR5a at {ROBOT_IP}...")
    
    with DobotRobot(ROBOT_IP) as robot:
        try:
            def connection_callback(is_conn):
                pass
            
            robot.EnableAutoReconnect(enable=True, callback=connection_callback)
            
            print("Connected! Initializing robot...")
            reset_motion_state(robot)
            print("✅ Robot initialized and in standby.")

            is_at_home = False
            is_away = False
            current_tele_pose = POSITIONS[-1].copy()

            # DIRECT OPTION SELECTION ON LAUNCH
            while True:
                while keyboard.is_pressed('enter'): pass 
                
                print("\n==========================================")
                print("🕹️  DOBOT CR5a CONTROL SYSTEM READY")
                print("==========================================")
                cmd = input("Options -> [start] [home] [pos4] [tele] [exit] : ").strip().lower()
                
                if cmd in ["start", "run"]:
                    print("\n🚀 Executing Sequence: Position 1 (Home) -> Position 4...")
                    
                    if not is_at_home:
                        print("Moving to Position 1 (Home) first...")
                        if not safe_move(robot, POSITIONS[0]):
                            print("❌ Could not reach Home. Aborting start.")
                            continue
                        time.sleep(WAIT_TIME)

                    success = True
                    for idx, pose in enumerate(POSITIONS):
                        print(f"Moving to Position {idx + 1}...")
                        if not safe_move(robot, pose):
                            success = False
                            break
                        time.sleep(WAIT_TIME)
                    
                    if success:
                        is_at_home = False
                        is_away = False
                        current_tele_pose = POSITIONS[-1].copy()
                        print("✅ Sequence finished! Robot is at Position 4.")
                        
                        if haptic_success:
                            use_touch = input("\nEnter Touch Control mode now? (y/n): ").strip().lower()
                            if use_touch in ['y', 'yes']:
                                current_tele_pose = run_teleoperation(robot, POSITIONS[-1].copy())
                                is_away = True

                elif cmd == "home":
                    if is_at_home:
                        print("Robot is already at Home (Position 1)!")
                    else:
                        if unwind_to_home(robot):
                            is_at_home = True
                            is_away = False
                        
                elif cmd in ["pos4", "pos 4"]:
                    print("Moving straight to Position 4...")
                    if force_move_to_pos4(robot):
                        is_at_home = False
                        is_away = False
                        current_tele_pose = POSITIONS[3].copy()

                elif cmd == "tele":
                    if haptic_success:
                        current_tele_pose = run_teleoperation(robot, current_tele_pose)
                        is_at_home = False
                        is_away = True
                    else:
                        print("❌ Haptic device is not connected.")
                    
                elif cmd == "exit":
                    print("Exiting script...")
                    break
                else:
                    print("Invalid command. Please enter [start], [home], [pos4], [tele], or [exit].")
                    
        except KeyboardInterrupt:
            print("\n\n[WARNING] Script interrupted manually (Ctrl+C).")
        except Exception as e:
            print(f"\n[ERROR] Unexpected crash: {e}")
        finally:
            print("\n--- INITIATING CLEANUP ---")
            try: 
                robot.motion.Stop()
                time.sleep(0.5)
            except: 
                pass
            
            close_haptic()
            print("✅ Cleanup complete. TCP mode maintained. Safe to run script again.")

if __name__ == "__main__":
    main()