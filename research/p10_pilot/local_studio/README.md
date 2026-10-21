# Yerel Docker Studio — 21 Ekim 2026

GenLayer Studio v0.121.6 / GenVM v0.2.16. API: http://127.0.0.1:4000/api,
arayüz: http://127.0.0.1:8080, yerel zincir: 61127. Beş mantıksal validator
aynı Docker kurulumunda çalışır; farklı kamu ağı işletmecileri değildir.

Windows PowerShell'de özgün WSL yapılandırmasını kullanın:

```powershell
docker compose -f '\\wsl$\Ubuntu-24.04\home\eser\aeropredict-ai\research\p10_pilot\local_studio\compose.yaml' up -d
```

Linux'ta Docker entegrasyonu etkinse proje kökünden:

```sh
docker compose -f research/p10_pilot/local_studio/compose.yaml up -d
```

`runtime.env.example` bu izole ortamın açık geliştirme ayarlarıdır; kişisel
anahtar veya RPC sırrı içermez. LLM anahtarı eklenmedi. Model/provider adları
validator metadatasıdır; sayısal tahmin constructor'ları ve Base strict_eq
probu LLM çağırmaz. LLM erişimi test edilmedi.

Servisler yalnız loopback HTTP portlarını yayımlar. Postgres, Redis ve GenVM
önbelleği `aeropredict-studio_*` adlı Docker volume'larında kalır. Verileri
koruyan durdurma komutu, aynı `-f` yolu ile `docker compose ... stop` olur.
Docker Desktop çalışır durumda olmalıdır. Windows başlangıç servisi kurulmadı.

`HARDHAT_URL` yalnız konteyner içindeki kullanılmayan 127.0.0.1:8545 adresidir.
Bu sürümün eski işlem ayrıştırıcısı, EVM düğümü çevrimdışıyken de Web3 codec
nesnesine ihtiyaç duyar. Yerel Studio'nun DB/GenVM mutabakatı kullanılır;
EVM rollup dağıtımı veya EVM protokol ücreti doğrulanmış sayılmaz.

Beş tahminin eski kayıtları değiştirilmeden altı yerel sözleşme ve bir gerçek
Base RPC probu çağrısı doğrulandı. İşlem hashleri ve çoğunluk oyları
`../studio_runs/local_20261021.json` içindedir. Üç agree / iki idle, beşinin
birden yürütüp onayladığı anlamına gelmez. Eski RPC probuna zorunlu SDK
bağımlılık başlığı eklendi; güncel Contract sınıfı kullanıldı.

67 Direct Mode testi yerel mantık testidir. Docker Studio kayıtları gerçek
yerel GenVM yürütmesidir. Hiçbiri Hosted Studio veya bağımsız kamu ağı
mutabakatı olarak gösterilmez. Gerçekleşen FEES ve tahmin isabeti ancak
29 Ekim 2026 00:00 UTC sonrasında ayrı kanıtla değerlendirilebilir.

Kaynak: https://github.com/genlayerlabs/genlayer-studio/releases/tag/v0.121.6
