# T-16: muse2api theo Đường A (upstream của CLIProxyAPI)

## Quyết định đã chốt (không tự đổi)

- Đường A (chủ dự án chốt 26/10/2026): muse2api làm upstream của
  CLIProxyAPI. MuLon KHÔNG gọi thẳng muse2api (không gọi cổng
  muse2api), KHÔNG nới `validate_proxy_base_url`.
- MuLon vẫn chỉ gọi model qua proxy local `127.0.0.1:8317` như mọi
  model khác. Phía sau proxy, CLIProxyAPI route prefix `muse` sang
  muse2api.
- Model trong MuLon: `muse/muse-spark` (model chat duy nhất của
  muse2api trong đợt này; media qua muse2api để đợt sau nếu chủ
  dự án yêu cầu).
- Key/phiên muse2api chỉ ở Vault hoặc cấu hình trên máy cài, không
  bao giờ commit key thật lên repo, chỉ dùng placeholder.

## Sơ đồ

```
Người dùng -> MuLon -> ModelGateway (model muse/muse-spark)
  -> proxy local 127.0.0.1:8317 (CLIProxyAPI)
    -> upstream muse2api (service local trên máy cài)
      -> tài khoản Muse trong pool muse2api -> muse.ai
```

MuLon (ở đường chat/model) không có đường nào đi thẳng tới muse2api. Module
`mulon/muse2api.py` chỉ sinh cấu hình upstream cho CLIProxyAPI và
kiểm tra tên model, không gọi HTTP.

## Cài đặt trên máy cài (không phải code MuLon)

1. Chạy muse2api riêng (Docker) trên máy cài, có ít nhất 1 tài khoản
   Muse trong pool của nó. Xem README của fork `mmmnhat/muse2api`.
2. Thêm upstream muse2api vào cấu hình CLIProxyAPI trên máy đó, theo
   mẫu `config/cliproxy-muse2api.example.yaml` trong repo. Thay
   placeholder key bằng key thật chỉ ở file cấu hình máy cài (hoặc
   Vault), không commit file đã điền key.
3. Chọn model trong MuLon: đặt `MODEL_BRAIN=muse/muse-spark` (hoặc
   chọn `muse/muse-spark` qua cơ chế chọn model khi khung T-14 hoàn
   thiện). Gõ `muse-spark` hoặc `muse/muse-spark` được chuẩn hóa về
   `openai/muse/muse-spark` qua alias trong `mulon/gateway.py` để LiteLLM
   định tuyến đúng tới proxy OpenAI-compatible local 8317.

## Nghiệm thu sống (bắt buộc, không chỉ unit test)

1. GET `/v1/models` qua proxy 8317 thấy `muse-spark`.
2. Một lượt chat MuLon với model Muse trả lời thật từ muse.ai.
3. Tắt muse2api: MuLon vẫn chạy model khác; chọn model Muse thì
   báo lỗi rõ ràng (degrade), không sập bot.
4. Grep toàn repo không có key thật của muse2api.

## Degrade và giới hạn còn lại

- Nếu muse2api chết, CLIProxyAPI trả lỗi, gateway báo
  `GatewayError` rõ ràng cho lượt đó. Các model khác vẫn gọi được
  qua cùng proxy, trừ khi circuit breaker của gateway đang mở sau
  nhiều lỗi liên tiếp (hành vi chung của gateway, không phải riêng
  T-16, cần test sống bước 3 để xác nhận).
- Cơ chế quản lý gateway của T-14 (LUỒNG 4 đang DOING) chưa xong
  khi làm T-16, nên đợt này chưa gắn cấu hình upstream vào UI quản
  lý gateway; cấu hình upstream nằm ở CLIProxyAPI trên máy cài
  theo mẫu trên. Khi T-14 xong, việc nối mẫu này vào UI đó là
  việc tiếp theo, không tự làm trong T-16 để tránh đụng LUỒNG 4.
