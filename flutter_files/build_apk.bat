@echo off
echo ========================================
echo  RDV Manager - Build APK
echo ========================================

REM 1. Generer la cle de signature (a faire UNE SEULE FOIS)
echo.
echo [1/3] Generation de la cle de signature...
keytool -genkey -v -keystore rdv_manager_key.jks -keyalg RSA -keysize 2048 -validity 10000 -alias rdv_manager ^
  -dname "CN=RDV Manager, OU=Dev, O=MJL, L=Paris, S=IDF, C=FR"

REM 2. Creer le fichier key.properties
echo.
echo [2/3] Creation de key.properties...
(
echo storePassword=changeme
echo keyPassword=changeme
echo keyAlias=rdv_manager
echo storeFile=../rdv_manager_key.jks
) > android\key.properties

REM 3. Build APK release
echo.
echo [3/3] Build de l'APK release...
flutter build apk --release

echo.
echo ========================================
echo  APK genere dans : build\app\outputs\flutter-apk\app-release.apk
echo ========================================
pause
