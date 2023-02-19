## written by ChenZhuo for captcha recognization
import os
import string
import torch
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from torchvision.transforms.functional import to_tensor, to_pil_image
import torchvision.transforms as T
import torchvision.datasets as dset
import torch
import torch.nn as nn
import torch.nn.functional as F
from collections import OrderedDict
import numpy as np
from tqdm import tqdm
from captcha.image import ImageCaptcha
import random


class Model(nn.Module):
    def __init__(self, n_classes, input_shape=(3, 64, 128)):
        super(Model, self).__init__()
        self.input_shape = input_shape
        channels = [32, 64, 128, 256, 256]
        layers = [2, 2, 2, 2, 2]
        kernels = [3, 3, 3, 3, 3]
        pools = [2, 2, 2, 2, (2, 1)]
        modules = OrderedDict()

        def cba(name, in_channels, out_channels, kernel_size):
            modules[f'conv{name}'] = nn.Conv2d(in_channels, out_channels, kernel_size, padding=(1, 1) if kernel_size == 3 else 0)
            modules[f'bn{name}'] = nn.BatchNorm2d(out_channels)
            modules[f'relu{name}'] = nn.ReLU(inplace=True)

        last_channel = 3
        for block, (n_channel, n_layer, n_kernel, k_pool) in enumerate(zip(channels, layers, kernels, pools)):
            for layer in range(1, n_layer + 1):
                cba(f'{block + 1}{layer}', last_channel, n_channel, n_kernel)
                last_channel = n_channel
            modules[f'pool{block + 1}'] = nn.MaxPool2d(k_pool)
        modules[f'dropout'] = nn.Dropout(0.25, inplace=True)

        self.cnn = nn.Sequential(modules)
        self.lstm = nn.LSTM(input_size=self.infer_features(), hidden_size=128, num_layers=2, bidirectional=True)
        self.fc = nn.Linear(in_features=256, out_features=n_classes)

    def infer_features(self):
        x = torch.zeros((1,) + self.input_shape)
        x = self.cnn(x)
        x = x.reshape(x.shape[0], -1, x.shape[-1])
        return x.shape[1]

    def forward(self, x):
        x = self.cnn(x)
        x = x.reshape(x.shape[0], -1, x.shape[-1])
        x = x.permute(2, 0, 1)
        x, _ = self.lstm(x)
        x = self.fc(x)
        return x

def decode(sequence):
    a = ''.join([characters[x] for x in sequence])
    s = ''.join([x for j, x in enumerate(a[:-1]) if x != characters[0] and x != a[j+1]])
    if len(s) == 0:
        return ''
    if a[-1] != characters[0] and s[-1] != a[-1]:
        s += a[-1]
    return s

def decode_target(sequence):
    return ''.join([characters[x] for x in sequence]).replace(' ', '')

def calc_acc(target, output):
    output_argmax = output.detach().permute(1, 0, 2).argmax(dim=-1)
    target = target.cpu().numpy()
    output_argmax = output_argmax.cpu().numpy()
    a = np.array([decode_target(true) == decode(pred) for true, pred in zip(target, output_argmax)])
    return a.mean()


def train(model, optimizer, epoch, dataloader):
    model.train()
    loss_mean = 0
    acc_mean = 0
    with tqdm(dataloader) as pbar:
        for batch_index, (data, target, input_lengths, target_lengths) in enumerate(pbar):

            optimizer.zero_grad()
            output = model(data)

            output_log_softmax = F.log_softmax(output, dim=-1)
            loss = F.ctc_loss(output_log_softmax, target, input_lengths, target_lengths)

            loss.backward()
            optimizer.step()

            loss = loss.item()
            acc = calc_acc(target, output)

            if batch_index == 0:
                loss_mean = loss
                acc_mean = acc

            loss_mean = 0.1 * loss + 0.9 * loss_mean
            acc_mean = 0.1 * acc + 0.9 * acc_mean

            pbar.set_description(f'Epoch: {epoch} Loss: {loss_mean:.4f} Acc: {acc_mean:.4f} ')


def valid(model, optimizer, epoch, dataloader):
    model.eval()
    with tqdm(dataloader) as pbar, torch.no_grad():
        loss_sum = 0
        acc_sum = 0
        for batch_index, (data, target, input_lengths, target_lengths) in enumerate(pbar):

            output = model(data)
            output_log_softmax = F.log_softmax(output, dim=-1)
            loss = F.ctc_loss(output_log_softmax, target, input_lengths, target_lengths)

            loss = loss.item()
            acc = calc_acc(target, output)

            loss_sum += loss
            acc_sum += acc

            loss_mean = loss_sum / (batch_index + 1)
            acc_mean = acc_sum / (batch_index + 1)

            pbar.set_description(f'Test : {epoch} Loss: {loss_mean:.4f} Acc: {acc_mean:.4f} ')


class CaptchaDataset(Dataset):
    def __init__(self, characters, length, width, height, input_length, label_length, img_path):
        super(CaptchaDataset, self).__init__()
        self.characters = characters
        self.length = length
        self.width = width
        self.height = height
        self.input_length = input_length
        self.label_length = label_length
        self.n_class = len(characters)
        self.generator = ImageCaptcha(width=width, height=height)
        input_list = [i for i in os.listdir(img_path) if i.endswith(".jpg")]
        print(input_list)
        self.img = [os.path.join(img_path, i) for i in input_list]
        self.target = [i.split(".")[0] for i in input_list]


    def __len__(self):
        return self.length

    def __getitem__(self, index):
        random_str = ''.join([random.choice(self.characters[1:]) for j in range(self.label_length)])
        # image = to_tensor(self.generator.generate_image(random_str))
        # target = torch.tensor([self.characters.find(x) for x in random_str], dtype=torch.long)
        image = to_tensor(Image.open(self.img[index]))
        target = torch.tensor([self.characters.find(x) for x in self.target[index]], dtype=torch.long)
        input_length = torch.full(size=(1,), fill_value=self.input_length, dtype=torch.long)
        target_length = torch.full(size=(1,), fill_value=self.label_length, dtype=torch.long)
        # print(image, target, input_length, target_length)
        return image, target, input_length, target_length


if __name__ == '__main__':
    characters = '-' + string.digits + string.ascii_uppercase
    width, height, n_len, n_classes = 192, 64, 4, len(characters)
    dataroot = "./data"

    # dataset = dset.ImageFolder(root=dataroot)
    # print(dataset)
    # indices = torch.randperm(len(dataset)).tolist()
    # dataset_train = torch.utils.data.Subset(dataset, indices[:1000])  # too large for full size
    # dataset_test = torch.utils.data.Subset(dataset, indices[1000:])
    #
    # dataloader_train = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, shuffle=True)
    # dataloader_test = torch.utils.data.DataLoader(dataset_test, batch_size=batch_size, shuffle=False)

    model = Model(n_classes, input_shape=(3, height, width))
    print(model)

    optimizer = torch.optim.Adam(model.parameters(), 1e-3, amsgrad=True)
    epochs = 10
    batch_size = 128
    n_input_length = 12
    train_set = CaptchaDataset(characters, 10000, width, height, n_input_length, n_len, "data/train")
    valid_set = CaptchaDataset(characters, 1000, width, height, n_input_length, n_len, "data/valid")
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    valid_loader = DataLoader(valid_set, batch_size=batch_size, shuffle=False)
    for epoch in range(1, epochs + 1):
        train(model, optimizer, epoch, train_loader)
        valid(model, optimizer, epoch, valid_loader)



    # model.eval()
    # do = True
    # while do or decode_target(target) == decode(output_argmax[0]):
    #     do = False
    #     image, target, input_length, label_length = dataset[0]
    #     print('true:', decode_target(target))
    #
    #     output = model(image.unsqueeze(0).cuda())
    #     output_argmax = output.detach().permute(1, 0, 2).argmax(dim=-1)
    #     print('pred:', decode(output_argmax[0]))
    # to_pil_image(image)