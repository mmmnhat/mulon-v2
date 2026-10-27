#!/usr/bin/env node
/**
 * Zalo Bridge cho MuLon (T-22.1)
 * Giao tiếp qua stdin / stdout dạng JSON line.
 * Thư viện: zca-js (Unofficial Zalo API).
 */

import readline from 'node:readline';

let Zalo = null;
let ThreadType = null;

try {
  const zca = await import('zca-js');
  Zalo = zca.Zalo;
  ThreadType = zca.ThreadType;
} catch (err) {
  // zca-js chưa cài đặt
}

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false
});

let apiInstance = null;
let currentZalo = null;

function send(data) {
  process.stdout.write(JSON.stringify(data) + '\n');
}

rl.on('line', async (line) => {
  if (!line.trim()) return;
  let req;
  try {
    req = JSON.parse(line);
  } catch (e) {
    send({ ok: false, error: 'Lỗi parse JSON: ' + e.message });
    return;
  }

  const { id = 1, cmd, args = {} } = req;

  if (!Zalo) {
    send({
      id,
      ok: false,
      error: 'Thư viện zca-js chưa được cài đặt. Hãy chạy "npm install zca-js" trong thư mục mulon/bridges/.'
    });
    return;
  }

  try {
    switch (cmd) {
      case 'ping':
        send({ id, ok: true, pong: true });
        break;

      case 'login_qr': {
        currentZalo = new Zalo({ selfListen: false });
        apiInstance = await currentZalo.loginQR({}, (qrPath) => {
          send({ event: 'qr_ready', qr_path: qrPath });
        });
        const ownId = typeof apiInstance.getOwnId === 'function' ? apiInstance.getOwnId() : 'unknown';
        send({
          id,
          ok: true,
          user: { id: ownId },
          session: apiInstance.session || {}
        });
        break;
      }

      case 'login_session': {
        currentZalo = new Zalo({ selfListen: false });
        apiInstance = await currentZalo.login({
          cookie: args.cookie,
          imei: args.imei,
          userAgent: args.userAgent
        });
        const ownId = typeof apiInstance.getOwnId === 'function' ? apiInstance.getOwnId() : 'unknown';
        send({ id, ok: true, user: { id: ownId } });
        break;
      }

      case 'get_messages': {
        if (!apiInstance) {
          send({ id, ok: false, error: 'Zalo chưa đăng nhập' });
          break;
        }
        // Giả lập đọc tin nhắn qua API hoặc trả về danh sách
        send({ id, ok: true, messages: [] });
        break;
      }

      case 'send_message': {
        if (!apiInstance) {
          send({ id, ok: false, error: 'Zalo chưa đăng nhập' });
          break;
        }
        const threadType = args.type === 'group' ? (ThreadType ? ThreadType.Group : 1) : (ThreadType ? ThreadType.User : 0);
        const res = await apiInstance.sendMessage({ msg: args.msg }, args.thread_id, threadType);
        send({ id, ok: true, result: res });
        break;
      }

      case 'send_file': {
        if (!apiInstance) {
          send({ id, ok: false, error: 'Zalo chưa đăng nhập' });
          break;
        }
        const threadType = args.type === 'group' ? (ThreadType ? ThreadType.Group : 1) : (ThreadType ? ThreadType.User : 0);
        const res = await apiInstance.sendMessage({
          msg: args.msg || '',
          attachments: [args.file_path]
        }, args.thread_id, threadType);
        send({ id, ok: true, result: res });
        break;
      }

      case 'find_user': {
        if (!apiInstance) {
          send({ id, ok: false, error: 'Zalo chưa đăng nhập' });
          break;
        }
        const user = await apiInstance.findUser(args.phone);
        send({ id, ok: true, user });
        break;
      }

      case 'listen': {
        if (!apiInstance) {
          send({ id, ok: false, error: 'Zalo chưa đăng nhập' });
          break;
        }
        if (apiInstance.listener) {
          apiInstance.listener.on('message', (msg) => {
            send({
              event: 'message',
              data: {
                threadId: msg.threadId,
                isGroup: msg.type === (ThreadType ? ThreadType.Group : 1),
                senderId: msg.data ? (msg.data.uidFrom || msg.data.from) : null,
                content: typeof msg.data?.content === 'string' ? msg.data.content : JSON.stringify(msg.data?.content),
                timestamp: msg.data?.timestamp || Date.now()
              }
            });
          });
          apiInstance.listener.start();
        }
        send({ id, ok: true, listening: true });
        break;
      }

      case 'logout': {
        apiInstance = null;
        send({ id, ok: true });
        break;
      }

      default:
        send({ id, ok: false, error: `Lệnh không hỗ trợ: ${cmd}` });
    }
  } catch (err) {
    send({ id, ok: false, error: err.message || String(err) });
  }
});
