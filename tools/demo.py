# -*- coding:utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import os, sys

sys.path.append("../")
import cv2
import numpy as np
from timeit import default_timer as timer
import argparse
import tensorflow as tf

from data.io.image_preprocess import short_side_resize_for_inference_data
from libs.networks import build_whole_network
from help_utils.tools import *
from libs.box_utils import draw_box_in_img
from libs.label_name_dict.label_dict import *
from help_utils import tools
from libs.box_utils import nms


def get_file_paths_recursive(folder=None, file_ext=None):
    """ Get the absolute path of all files in given folder recursively
    :param folder:
    :param file_ext:
    :return:
    """
    file_list = []
    if folder is None:
        return file_list

    for dir_path, dir_names, file_names in os.walk(folder):
        for file_name in file_names:
            if file_ext is None:
                file_list.append(os.path.join(dir_path, file_name))
                continue
            if file_name.endswith(file_ext):
                file_list.append(os.path.join(dir_path, file_name))
    return file_list


def inference(det_net, file_paths, des_folder, h_len, w_len, h_overlap, w_overlap, save_res=False):

    if save_res:
        assert cfgs.SHOW_SCORE_THRSHOLD >= 0.5, \
            'please set score threshold (example: SHOW_SCORE_THRSHOLD = 0.5) in cfgs.py'

    else:
        assert cfgs.SHOW_SCORE_THRSHOLD <= 0.005, \
            'please set score threshold (example: SHOW_SCORE_THRSHOLD = 0.00) in cfgs.py'

    # 1. preprocess img
    img_plac = tf.placeholder(dtype=tf.uint8, shape=[None, None, 3])
    img_batch = tf.cast(img_plac, tf.float32)
    if cfgs.NET_NAME in ['resnet101_v1d']:
        img_batch = (img_batch / 255 - tf.constant(cfgs.PIXEL_MEAN_)) / tf.constant(cfgs.PIXEL_STD)
    else:
        img_batch = img_batch - tf.constant(cfgs.PIXEL_MEAN)

    img_batch = tf.expand_dims(img_batch, axis=0)
    img_batch = short_side_resize_for_inference_data(img_tensor=img_batch,
                                                     target_shortside_len=cfgs.IMG_SHORT_SIDE_LEN,
                                                     is_resize=False)

    det_boxes_h, det_scores_h, det_category_h = det_net.build_whole_detection_network(input_img_batch=img_batch,
                                                                                      gtboxes_batch=None)

    init_op = tf.group(
        tf.global_variables_initializer(),
        tf.local_variables_initializer()
    )

    restorer, restore_ckpt = det_net.get_restorer()

    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True

    with tf.Session(config=config) as sess:
        sess.run(init_op)
        if not restorer is None:
            restorer.restore(sess, restore_ckpt)
            print('restore model')

        if not os.path.exists('./tmp.txt'):
            fw = open('./tmp.txt', 'w')
            fw.close()

        fr = open('./tmp.txt', 'r')
        pass_img = fr.readlines()
        fr.close()

        for count, img_path in enumerate(file_paths):
            fw = open('./tmp.txt', 'a+')
            if img_path + '\n' in pass_img:
                continue
            start = timer()
            img = cv2.imread(img_path)

            box_res = []
            label_res = []
            score_res = []

            imgH = img.shape[0]
            imgW = img.shape[1]

            if imgH < h_len:
                temp = np.zeros([h_len, imgW, 3], np.float32)
                temp[0:imgH, :, :] = img
                img = temp
                imgH = h_len

            if imgW < w_len:
                temp = np.zeros([imgH, w_len, 3], np.float32)
                temp[:, 0:imgW, :] = img
                img = temp
                imgW = w_len

            for hh in range(0, imgH, h_len - h_overlap):
                if imgH - hh - 1 < h_len:
                    hh_ = imgH - h_len
                else:
                    hh_ = hh
                for ww in range(0, imgW, w_len - w_overlap):
                    if imgW - ww - 1 < w_len:
                        ww_ = imgW - w_len
                    else:
                        ww_ = ww
                    src_img = img[hh_:(hh_ + h_len), ww_:(ww_ + w_len), :]

                    det_boxes_h_, det_scores_h_, det_category_h_ = \
                        sess.run(
                            [det_boxes_h, det_scores_h, det_category_h],
                            feed_dict={img_plac: src_img[:, :, ::-1]}
                        )

                    if len(det_boxes_h_) > 0:
                        for ii in range(len(det_boxes_h_)):
                            box = det_boxes_h_[ii]
                            box[0] = box[0] + ww_
                            box[1] = box[1] + hh_
                            box[2] = box[2] + ww_
                            box[3] = box[3] + hh_
                            box_res.append(box)
                            label_res.append(det_category_h_[ii])
                            score_res.append(det_scores_h_[ii])

            box_res = np.array(box_res)
            label_res = np.array(label_res)
            score_res = np.array(score_res)

            box_res_, label_res_, score_res_ = [], [], []

            h_threshold = {'roundabout': 0.35, 'tennis-court': 0.35, 'swimming-pool': 0.4, 'storage-tank': 0.3,
                           'soccer-ball-field': 0.3, 'small-vehicle': 0.4, 'ship': 0.35, 'plane': 0.35,
                           'large-vehicle': 0.4, 'helicopter': 0.4, 'harbor': 0.3, 'ground-track-field': 0.4,
                           'bridge': 0.3, 'basketball-court': 0.4, 'baseball-diamond': 0.3}

            for sub_class in range(1, cfgs.CLASS_NUM + 1):
                index = np.where(label_res == sub_class)[0]
                if len(index) == 0:
                    continue
                tmp_boxes_h = box_res[index]
                tmp_label_h = label_res[index]
                tmp_score_h = score_res[index]

                tmp_boxes_h = np.array(tmp_boxes_h)
                tmp = np.zeros([tmp_boxes_h.shape[0], tmp_boxes_h.shape[1] + 1])
                tmp[:, 0:-1] = tmp_boxes_h
                tmp[:, -1] = np.array(tmp_score_h)

                inx = nms.py_cpu_nms(dets=np.array(tmp, np.float32),
                                     thresh=h_threshold[LABEl_NAME_MAP[sub_class]],
                                     max_output_size=500)

                box_res_.extend(np.array(tmp_boxes_h)[inx])
                score_res_.extend(np.array(tmp_score_h)[inx])
                label_res_.extend(np.array(tmp_label_h)[inx])

            time_elapsed = timer() - start

            if save_res:

                scores = np.array(score_res_)
                labels = np.array(label_res_)
                boxes = np.array(box_res_)
                valid_show = scores > cfgs.SHOW_SCORE_THRSHOLD
                scores = scores[valid_show]
                boxes = boxes[valid_show]
                labels = labels[valid_show]

                det_detections_h = draw_box_in_img.draw_boxes_with_label_and_scores(np.array(img, np.float32),
                                                                                    boxes=np.array(boxes),
                                                                                    labels=np.array(labels),
                                                                                    scores=np.array(scores),
                                                                                    in_graph=False)

                save_dir = os.path.join(des_folder, cfgs.VERSION)
                tools.mkdir(save_dir)
                cv2.imwrite(save_dir + '/' + img_path.split('/')[-1].split('.')[0] + '_h.jpg',
                            det_detections_h)

                view_bar('{} cost {}s'.format(img_path.split('/')[-1].split('.')[0],
                                              time_elapsed), count + 1, len(file_paths))

            else:
                # eval txt
                CLASS_DOTA = NAME_LABEL_MAP.keys()

                # Task2
                write_handle_h = {}
                txt_dir_h = os.path.join('txt_output', cfgs.VERSION + '_h')
                tools.mkdir(txt_dir_h)
                for sub_class in CLASS_DOTA:
                    if sub_class == 'back_ground':
                        continue
                    write_handle_h[sub_class] = open(os.path.join(txt_dir_h, 'Task2_%s.txt' % sub_class), 'a+')

                for i, hbox in enumerate(box_res_):
                    command = '%s %.3f %.1f %.1f %.1f %.1f\n' % (img_path.split('/')[-1].split('.')[0],
                                                                 score_res_[i],
                                                                 hbox[0], hbox[1], hbox[2], hbox[3])
                    write_handle_h[LABEl_NAME_MAP[label_res_[i]]].write(command)

                for sub_class in CLASS_DOTA:
                    if sub_class == 'back_ground':
                        continue
                    write_handle_h[sub_class].close()

            view_bar('%s cost %.3fs' % (img_path.split('/')[-1].split('.')[0],
                                        time_elapsed), count + 1, len(file_paths))
            fw.write('{}\n'.format(img_path))
            fw.close()
        os.remove('./tmp.txt')


def parse_args():
    """
    Parse input arguments
    """
    parser = argparse.ArgumentParser(description='Train a Fast R-CNN network')
    parser.add_argument('--src_folder', dest='src_folder',
                        help='images path',
                        default=None, type=str)
    parser.add_argument('--des_folder', dest='des_folder',
                        help='output path',
                        default=None, type=str)
    parser.add_argument('--h_len', dest='h_len',
                        help='image height',
                        default=800, type=int)
    parser.add_argument('--w_len', dest='w_len',
                        help='image width',
                        default=800, type=int)
    parser.add_argument('--h_overlap', dest='h_overlap',
                        help='height overlap',
                        default=200, type=int)
    parser.add_argument('--w_overlap', dest='w_overlap',
                        help='width overlap',
                        default=200, type=int)
    parser.add_argument('--image_ext', dest='image_ext',
                        help='image format',
                        default='.png', type=str)
    parser.add_argument('--save_res', dest='save_res',
                        help='save results',
                        default=True, type=bool)
    parser.add_argument('--gpu', dest='gpu',
                        help='gpu index',
                        default='0', type=str)

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    # args = parse_args()
    # print('Called with args:')
    # print(args)

    # os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
    os.environ["CUDA_VISIBLE_DEVICES"] = '0'

    # file_paths = get_file_paths_recursive(args.src_folder, args.image_ext)
    #
    # det_net = build_whole_network.DetectionNetwork(base_network_name=cfgs.NET_NAME,
    #                                                is_training=False)
    #
    # inference(det_net, file_paths, args.des_folder, args.h_len, args.w_len,
    #            args.h_overlap, args.w_overlap,  args.save_res)

    file_paths = get_file_paths_recursive('/unsullied/sharefs/yangxue/isilon/yangxue/data/DOTA/test/images', '.png')
    det_net = build_whole_network.DetectionNetwork(base_network_name=cfgs.NET_NAME,
                                                   is_training=False)
    inference(det_net, file_paths, './demos/', 800, 800,
              200, 200, False)
