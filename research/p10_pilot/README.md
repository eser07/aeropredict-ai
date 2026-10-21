# P10 yerel GenLayer pilotu

Beş havuz: #64, #35, #0, #1, #4. Model, aynı tokenın son dört tamamlanmış haftadaki ham FEES ortalamasıdır; LLM tahmini değildir. Kayıtlar yerel dosyalardır, bağımsız zaman damgası sağlamaz.

Aktif kayıt: registrations/pilot_v2_20261018_r2.json. Önceki kayıtlar korunur. Yeni verifier kaydı gerektiğinde önceki JSON üzerine yazmayın; yeni dosya oluşturun. Son test raporu direct_test_report.json içindedir; panel kaynak hashlerini kontrol eder.

Doğrudan test kurulumu: Python 3.12+ içinde `python -m pip install -r requirements-p10-test.txt`.

Proje kökünden yalnızca Direct Mode'u çalıştırın:

```sh
python scripts/run_p10_direct_tests.py --cache .test-cache/gltest-direct --report .test-cache/p10-direct-tests.json
```

Paket ayrı dizine kurulmuşsa `--runtime-path <paket_dizini>` kullanın. SDK sürümü v0.2.12; runner hash'i sözleşme başlığında sabitlenmiştir. İlk çalıştırmada resmî GenVM sürümü indirilir. Windows'ta SDK stdin taşınması için aynı calldata'yı ileten pipe uyarlaması kullanılır. Bu uyarlama test aracına aittir, GenVM ağ doğrulaması değildir.

Test runner, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` kullanarak yalnızca Direct Mode eklentisini yükler. Studio test eklentisinin varsayılan artifacts temizliğini tetiklemez. Genel `pytest` çağrısı bu korumayı sağlamaz; pilot kayıtları bu yüzden artifacts dışında tutulur.

67 test: önceki verifier/pilot/yaşam döngüsü için 33, kanıt toplama ve dosya okuma kontrolleri için 31, SDK başlığı sabitlenmiş Base RPC probu için 3. Kontrollü Base RPC yanıtları kullanılır. Beş havuz eşleşmesi, validator replay uyuşması/uyuşmazlığı, yanlış zincir, yanlış FEES sözleşmesi, yanlış dönem, parent hash, blok yeniden örgütlenmesi, finality yüksekliği, ABI hataları, geç kayıt, veri yetersizliği ve tekrar deneme kapsanır. 21 Ekim çalıştırmasında 67 test geçti. Önceki 64 testlik rapor test_reports/direct_20261018.json içinde korunur.

Yeni verifier her tahmini constructor içinde kaydeder. Base Voter üzerinden havuz/gauge/FEES eşleşmesini, 7 günlük süreyi, ilk dönem sonu bloğunu, parent bağını ve finalized yüksekliğini kontrol eder; eth_call blockHash/requireCanonical ile sabitlenir. Tahmin isabeti, gerçekleşen verinin doğrulanmasından ayrı tutulur. Başarılı/başarısız tahmin tekrar yerleştirilemez; yetersiz veri yeniden denenebilir.

Veri yetersizliği bir validator'ın kanıt alamadığı durumdur. GenLayer strict_eq anlaşmazlığı işlem seviyesinde ayrıca başarısız olabilir. Burada bağımsız GenLayer ağı finality'si test edilmedi.

Studio — 21 Ekim güncellemesi: Docker ve WSL komutları gerekli komut izinleriyle erişilebilir. Yerel Docker Studio v0.121.6, GenVM v0.2.16 ve genlayer-js 1.1.8 ile API 127.0.0.1:4000/api, arayüz 127.0.0.1:8080 üzerinde çalıştırıldı. Zincir kimliği 61127, kayıtlı validator sayısı beştir. Beş mevcut tahmin, kaynak/taahhüt hashleri değiştirilmeden yerel sözleşmelere kaydedildi; işlemler FINALIZED, tahmin durumları PENDING olarak okundu. Eski pilot dosyaları değiştirilmedi.

BaseRpcProbe için eksik SDK bağımlılık başlığı ve eski Contract sınıfı düzeltildi. Gerçek Base RPC eth_chainId okuması GenVM strict_eq içinden 8453 döndürdü; kayıtta üç agree, iki idle oyu vardır. Bu, tek yerel kurulumun validator çoğunluğudur; farklı işletmecilerden bağımsız kamu ağı mutabakatı değildir. Hosted Studio dağıtımı için açık kullanıcı onayı hâlâ beklenir.

Yapılandırma local_studio/, tamamlanan işlem kanıtı studio_runs/local_20261021.json içindedir. Ortamda LLM anahtarı yoktur. Validator model adları metadata olarak bulunur; bu sözleşmeler exec_prompt çağırmaz. Sayısal probun gerçek web erişimi LLM model erişimini kanıtlamaz. Yerel test bakiyesi gerçek fon değildir; simülatörün gas_used=0 kaydı kamu ağının protokol ücretini veya USD maliyetini göstermez. Bilinmeyen USD alanları null kalır.

Dönem 22–29 Ekim 2026 UTC'dir; gerçekleşen FEES ve tahmin isabeti henüz yoktur. Dönem sonunda salt okunur toplayıcıyla gerçek kanıt alınması, ardından ayrıca doğrulanmış GenLayer settlement değerlendirmesi gerekir. Erken settlement yapılmadı; kamu ağı/testnet dağıtımı, kişisel cüzdan işlemi, ücretli hizmet veya git push yapılmadı.

Resmî belgeler: https://docs.genlayer.com/developers/intelligent-contracts/testing


## Salt okunur gerçekleşen veri toplayıcısı

`python scripts/p10_evidence.py` sadece beş doğrulanmış pilot kaydını işler. Hedef dönem bitmeden RPC istemcisi oluşturmaz. Dönem bittikten sonra Base finalized başlığında ikili aramayla ilk dönem sonu bloğunu bulur; aynı blok hashinde havuz/gauge/FEES eşleşmesini ve ham ödülü okur. İşlem gönderen RPC yöntemleri izin listesinde bulunmaz. Varsayılan RPC https://mainnet.base.org; isteğe bağlı BASE_RPC_URL ortam değişkeni okunur, .env dosyası açılmaz. URL/anahtar/sağlayıcı hata mesajı loga veya kontrol kaydına yazılmaz.

Çıktılar observations/ altında içerik hashine göre adlandırılır ve yalnızca yeni dosya olarak oluşturulur. Eski kontrol kaydı, tahmin kaydı veya tarihsel dataset üzerine yazılmaz. Bunlar yerel sağlayıcı gözlemleridir; kriptografik zincir kanıtı, değiştirilemez kayıt veya GenLayer mutabakatı değildir.

Panel en fazla son 256 kontrol dosyasını okur. Dosya hashini, tahmin kimliğini, dönemi ve kanıt alanlarını yeniden kontrol eder. İleri tarihli veya bozuk dosyaları yok sayar. Yeni bir başarısız okuma önceki geçerli yerel gözlemi silmez; son deneme bilgisi ayrıca gösterilir. Gerçekleşen değer ancak tamamlanmış dönem için geçerli bir yerel gözlem varsa görünür.

18 Ekim 2026 kontrolü: beş pending kaydı, sıfır RPC çağrısı. Studio/Docker ve WSL engeli sürüyor. İki açık Base RPC adresine ayrı bağlantı kontrolü HTTP 403 döndürdü; canlı zincir doğrulaması başarılı sayılmadı. Özgün Windows saatlik yenileme görevi değiştirilmedi. Kullanıcının sürekli devam etme isteği üzerine bu Codex sohbetinde ayrı saatlik devam görevi etkinleştirildi; yerel uygulama ve bilgisayar açık olmalıdır. Anlamlı ilerleme, tamamlanma veya gereken kullanıcı müdahalesi dışında aynı engeli tekrar bildirmez.


## GenLayer maliyet, fayda ve teşvik kontrolü — 18 Ekim 2026

Bu çalışma ücretli RPC/LLM hizmeti etkinleştirmedi ve gerçek ağ işlemi göndermedi.
Direct Mode yerel CPU/disk kullanır; ağ validator maliyeti bu testlerden
ölçülemez. Resmî güncel belgelere göre Studio'nun EVM katmanındaki sıfır gas,
GenLayer protokol ücretinin sıfır olduğu anlamına gelmez. Ağ aşamasında önce
yerel fee profile, güncel tahmin ve finalized receipt ile ölçüm gerekir.
[Studio sınırları](https://docs.genlayer.com/developers/intelligent-contracts/tools/genlayer-studio/limitations),
[dağıtım ve ücret profili](https://docs.genlayer.com/developers/intelligent-contracts/deploying).

Bu prototipin faydası, tahmin/veri kaynağı/dönem/değerlendirme kuralını birlikte
saklamak ve eksik kanıtı başarısız tahminden ayırmaktır. Gelecekte bağımsız
validator tekrarları tek uygulamanın kararına bağımlılığı azaltabilir. Aynı RPC
kaynağından gelen yanlış veriye karşı kendiliğinden doğruluk garantisi vermez.
Sayısal FEES eşleştirmesi için LLM zorunlu değildir; mevcut model dört haftalık
ham token ortalamasıdır.

Resmî Portal, builder/validator/community katkıları ve GenLayer Points programını
tanıtıyor. Katkıların kabul ve inceleme süreci bulunuyor. Yerel test geçirmek
AeroPredict'e otomatik puan veya ödül kazandırdığını kanıtlamaz; hesap uygunluğu,
başvuru ve kabul durumu doğrulanmadı, başvuru yapılmadı. Points için kazanç
öngörüsü kullanılmamalıdır. Portal ana sayfası ile açıklama sayfasındaki sezon
metinleri aynı gün farklılık gösterdiğinden sabit puan oranı veya sezon durumu
taahhüt edilmedi.
[Portal](https://portal.genlayer.foundation/),
[katkıların inceleme süreci](https://portal.genlayer.foundation/how-it-works/),
[resmî builder duyurusu ve şartlar](https://talks.genlayer.foundation/t/introducing-genlayers-incentivized-builders-program/20).
