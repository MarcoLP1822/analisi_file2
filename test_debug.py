#!/usr/bin/env python3
"""
Test script per verificare il funzionamento dell'API Document Validator.
"""
import requests
import json
import sys
from pathlib import Path

def test_api_health(base_url="http://127.0.0.1:8000"):
    """Test dell'endpoint di health check"""
    try:
        response = requests.get(f"{base_url}/api/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ API Health Check: {data['message']} v{data['version']}")
            return True
        else:
            print(f"❌ API Health Check fallito: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Errore di connessione API: {e}")
        return False

def test_frontend(base_url="http://127.0.0.1:8000"):
    """Test dell'endpoint frontend"""
    try:
        response = requests.get(base_url, timeout=5, allow_redirects=False)
        if response.status_code == 307:  # Redirect
            print("✅ Frontend redirect configurato correttamente")
            return True
        else:
            print(f"❌ Frontend test fallito: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Errore di connessione Frontend: {e}")
        return False

def check_libreoffice():
    """Verifica se LibreOffice è installato"""
    import subprocess
    try:
        result = subprocess.run(
            ["soffice", "--version"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        if result.returncode == 0:
            print(f"✅ LibreOffice installato: {result.stdout.strip()}")
            return True
        else:
            print("❌ LibreOffice non risponde correttamente")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ LibreOffice non trovato nel PATH")
        print("   Installa LibreOffice per abilitare la conversione documenti")
        return False

def main():
    print("🔍 Test Document Validator API")
    print("=" * 50)
    
    # Check se il server è in esecuzione
    ports_to_try = [8000, 8001, 8002, 8003]
    api_available = False
    base_url = None
    
    for port in ports_to_try:
        test_url = f"http://127.0.0.1:{port}"
        if test_api_health(test_url):
            api_available = True
            base_url = test_url
            break
    
    if not api_available:
        print("\n❌ Server non raggiungibile su nessuna porta testata")
        print("   Avvia il server con: python main.py")
        return False
    
    print(f"\n🌐 Server trovato su: {base_url}")
    
    # Test dei componenti
    tests_passed = 0
    total_tests = 3
    
    # Test 1: API Health
    if test_api_health(base_url):
        tests_passed += 1
    
    # Test 2: Frontend
    if test_frontend(base_url):
        tests_passed += 1
    
    # Test 3: LibreOffice
    if check_libreoffice():
        tests_passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 Risultati: {tests_passed}/{total_tests} test superati")
    
    if tests_passed == total_tests:
        print("🎉 Tutti i test sono passati! L'applicazione funziona correttamente.")
    elif tests_passed >= 2:
        print("⚠️  L'applicazione funziona ma alcuni componenti potrebbero mancare.")
    else:
        print("❌ Molti test falliti. Controlla la configurazione.")
    
    return tests_passed >= 2

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
