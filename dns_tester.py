import os
import shutil
import subprocess
import time
import csv
import socket
from concurrent.futures import ThreadPoolExecutor

def load_config(config_file):
    """Загружает параметры из конфигурационного файла."""
    config = {}
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except FileNotFoundError:
        print(f"Ошибка: Конфигурационный файл {config_file} не найден.")
    return config

def wait_for_port(port, timeout):
    """Ожидает открытия TCP порта в течение заданного времени."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False

def check_resolver(args):
    """Функция проверки одного резолвера."""
    idx, res_file, total_ips, cfg_params = args
    
    ip_to_check = ""
    try:
        with open(res_file, 'r', encoding='utf-8') as f:
            ip_to_check = f.read().strip()
    except Exception as e:
        return f"[{idx+1}/{total_ips}] Ошибка чтения {res_file}: {e}", False, 0, None

    executable = cfg_params['executable']
    dnsvpn_config = cfg_params['dnsvpn_config']
    link = cfg_params['link']
    start_port = cfg_params['start_port']
    timeout_thread = cfg_params['timeout_thread']
    timeout_curl = cfg_params['timeout_curl']
    minspeed = cfg_params['minspeed']
    
    current_port = start_port + idx
    process_executable = None
    
    try:
        # 2.1 Запуск исполняемого файла
        cmd_exe = [executable, "-c", dnsvpn_config, "-resolvers", res_file, "-listen-port", str(current_port)]
        process_executable = subprocess.Popen(cmd_exe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 2.2 Ожидание открытия порта вместо фиксированного sleep_time
        # Ждем открытия порта в течение timeout_thread секунд
        port_opened = wait_for_port(current_port, timeout_thread)
        
        if not port_opened:
            if os.path.exists(res_file):
                os.remove(res_file)
            return f"[{idx+1}/{total_ips}] {ip_to_check} BAD (Port {current_port} not opened)", False, 0, ip_to_check

        # 2.3 Порт открыт, запускаем curl с его собственным таймаутом
        cmd_curl = [
            "curl", 
            "-x", f"socks5://127.0.0.1:{current_port}", 
            "-m", str(timeout_curl), 
            "--write-out", "%{speed_download}", 
            "-o", "NUL" if os.name == 'nt' else "/dev/null", 
            link
        ]
        
        process_curl = subprocess.run(cmd_curl, capture_output=True, text=True, timeout=timeout_curl + 2)
        speed_val = process_curl.stdout.strip()
        speed = float(speed_val) if speed_val else 0.0
        
        # 2.4 Анализ скорости
        if speed >= minspeed and speed > 0:
            return f"[{idx+1}/{total_ips}] {ip_to_check} OK (Speed: {speed})", True, speed, ip_to_check
        else:
            if os.path.exists(res_file):
                os.remove(res_file)
            return f"[{idx+1}/{total_ips}] {ip_to_check} BAD (Speed: {speed} < {minspeed})", False, 0, ip_to_check
            
    except (subprocess.TimeoutExpired, Exception) as e:
        if os.path.exists(res_file):
            os.remove(res_file)
        return f"[{idx+1}/{total_ips}] {ip_to_check} BAD (Error: {e})", False, 0, ip_to_check
    finally:
        if process_executable:
            process_executable.terminate()
            try:
                process_executable.wait(timeout=1)
            except:
                process_executable.kill()

def main():
    config_path = 'tester_config.txt'
    cfg = load_config(config_path)
    if not cfg: return
    
    try:
        cfg_params = {
            'executable': cfg.get('executable'),
            'resolvers': cfg.get('resolvers'),
            'dnsvpn_config': cfg.get('dnsvpn_config'),
            'link': cfg.get('link'),
            'start_port': int(cfg.get('start_port', 1080)),
            'timeout_thread': int(cfg.get('timeout_thread', 30)),
            'timeout_curl': int(cfg.get('timeout_curl', 10)),
            'minspeed': float(cfg.get('minspeed', 0)),
            'threads': int(cfg.get('threads', 1))
        }
    except ValueError as e:
        print(f"Ошибка конфигурации: {e}")
        return
    
    temp_dir = 'temp_resolvers'
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    try:
        with open(cfg_params['resolvers'], 'r', encoding='utf-8') as f:
            ips = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Ошибка: Файл резолверов не найден.")
        return

    total_ips = len(ips)
    for i, ip in enumerate(ips):
        with open(os.path.join(temp_dir, f"res_{i}.txt"), 'w', encoding='utf-8') as f:
            f.write(ip)

    resolver_files = sorted([os.path.join(temp_dir, f) for f in os.listdir(temp_dir)])
    tasks = [(idx, res_file, total_ips, cfg_params) for idx, res_file in enumerate(resolver_files)]
    
    checked_count = 0
    deleted_count = 0
    results_csv = 'results.csv'
    
    with open(results_csv, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['ip', 'speed'])

        with ThreadPoolExecutor(max_workers=cfg_params['threads']) as executor:
            for result_msg, is_ok, speed, ip in executor.map(check_resolver, tasks):
                print(result_msg)
                checked_count += 1
                if is_ok:
                    writer.writerow([ip, speed])
                else:
                    deleted_count += 1

    print(f"\n--- Итог проверки ---")
    print(f"Всего проверено IP: {checked_count}")
    print(f"Удалено плохих IP: {deleted_count}")

if __name__ == "__main__":
    main()
